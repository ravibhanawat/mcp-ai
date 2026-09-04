"""
Report-agent routing tests — no Ollama and no database required.

These cover the keyword fallback path (`_hardcoded_generate`), which is what
actually serves a chart request whenever the LLM planner is unavailable or
returns malformed JSON. The SAP module functions are patched, so the tests
exercise routing decisions rather than seed data.
"""
import unittest
from decimal import Decimal
from unittest.mock import patch

from agent.report_agent import (
    ACCESS_DENIED,
    _REPORT_TOOLS,
    _validated_payload,
    _aggregate,
    _sanitize_parameters,
    _sanitize_title,
    _detect_chart_type,
    _detect_data_source,
    _hardcoded_generate,
    clarify_text,
    is_explicit_chart_request,
    is_report_query,
)


# ── Intent detection ──────────────────────────────────────────────────────────
class TestDetectDataSource(unittest.TestCase):

    def test_customer_info_query_routes_to_customer_source(self):
        """A customer-master request must not fall through to HR headcount."""
        self.assertEqual(
            _detect_data_source("Get customer info for C001 and show me in bar chart"),
            "sd_customer",
        )

    def test_bare_customer_query_routes_to_customer_source(self):
        self.assertEqual(_detect_data_source("customer C001 as a pie chart"), "sd_customer")

    def test_open_sales_orders_still_routes_to_sd_orders(self):
        """Adding the customer source must not steal the sales-order queries."""
        self.assertEqual(
            _detect_data_source("open sales orders by customer as bar chart"),
            "sd_orders",
        )

    def test_headcount_query_still_routes_to_hr(self):
        self.assertEqual(_detect_data_source("headcount by department bar chart"),
                         "hr_headcount")

    def test_unmatched_query_has_no_data_source(self):
        """'show me in bar chart' names no data — it must not silently pick HR."""
        self.assertIsNone(_detect_data_source("show me in bar chart"))

    def test_reorder_query_still_routes_to_reorder_alerts(self):
        """"reorder" and "material" both match — reorder must keep priority."""
        self.assertEqual(_detect_data_source("materials needing reorder bar chart"),
                         "mm_reorder")

    def test_customer_order_query_still_routes_to_sd_orders(self):
        self.assertEqual(_detect_data_source("customer order chart"), "sd_orders")

    def test_leave_and_salary_queries_route_to_hr(self):
        """These reached HR only via the removed default — keywords now carry them."""
        self.assertEqual(_detect_data_source("leave balance for EMP001 chart"),
                         "hr_headcount")
        self.assertEqual(_detect_data_source("salary breakdown EMP002 pie chart"),
                         "hr_headcount")

    def test_chart_type_and_report_intent_unchanged(self):
        q = "Get customer info for C001 and show me in bar chart"
        self.assertTrue(is_report_query(q))
        self.assertEqual(_detect_chart_type(q), "bar")


# ── Hardcoded fallback routing ────────────────────────────────────────────────
_FAKE_ORDERS = {
    "status": "OK",
    "customer_name": "Mahindra & Mahindra Ltd",
    "orders": [
        {"order_id": "SO5001", "material": "Steel Coil", "qty": 5.0,
         "value": 14000000.0, "status": "OPEN", "delivery_date": "2025-03-31"},
        {"order_id": "SO5011", "material": "Bearing", "qty": 15.0,
         "value": 630000.0, "status": "IN_TRANSIT", "delivery_date": "2025-02-20"},
    ],
    "total_orders": 2,
    "total_value": 14630000.0,
    "currency": "INR",
}

_FAKE_CUSTOMER = {
    "status": "OK",
    "customer_id": "C001",
    "name": "Mahindra & Mahindra Ltd",
    "city": "Mumbai",
    "credit_limit": 50000000.0,
    "currency": "INR",
    "payment_terms": "NET30",
    "status_flag": "ACTIVE",
}


class TestHardcodedCustomerChart(unittest.TestCase):

    def test_customer_chart_uses_that_customers_orders(self):
        with patch("modules.sd.get_customer_orders", return_value=_FAKE_ORDERS), \
             patch("modules.sd.get_customer_info",   return_value=_FAKE_CUSTOMER):
            payload = _hardcoded_generate(
                "Get customer info for C001 and show me in bar chart", None)

        self.assertIsNotNone(payload, "no chart produced for a customer query")
        self.assertEqual(payload["chart_type"], "bar")
        self.assertIn("C001", payload["title"])
        self.assertNotIn("Headcount", payload["title"])
        labels = [d["label"] for d in payload["data"]]
        self.assertIn("SO5001", " ".join(labels))
        self.assertTrue(all(d["value"] > 0 for d in payload["data"]))

    def test_customer_without_orders_falls_back_to_credit_profile(self):
        empty = {**_FAKE_ORDERS, "orders": [], "total_orders": 0, "total_value": 0.0}
        with patch("modules.sd.get_customer_orders", return_value=empty), \
             patch("modules.sd.get_customer_info",   return_value=_FAKE_CUSTOMER):
            payload = _hardcoded_generate("customer info C001 bar chart", None)

        self.assertIsNotNone(payload)
        self.assertIn("C001", payload["title"])
        self.assertTrue(payload["data"], "credit profile produced no data points")

    def test_unknown_customer_yields_no_chart(self):
        err = {"status": "ERROR", "message": "Customer C999 not found"}
        with patch("modules.sd.get_customer_orders", return_value=err), \
             patch("modules.sd.get_customer_info",   return_value=err):
            payload = _hardcoded_generate("customer info C999 bar chart", None)
        self.assertIsNone(payload)

    def test_customer_query_without_id_uses_portfolio_view(self):
        """'customer breakdown as a chart' has no ID — aggregate, don't guess one."""
        with patch("modules.sd.list_open_sales_orders",
                   return_value={"status": "OK", "open_orders": [
                       {"customer": "Mahindra & Mahindra Ltd"},
                       {"customer": "Tata Motors"},
                       {"customer": "Tata Motors"},
                   ]}):
            payload = _hardcoded_generate("customer breakdown as a chart", None)
        self.assertIsNotNone(payload)
        self.assertTrue(payload["data"])

    def test_query_naming_no_data_source_yields_no_chart(self):
        """A pure 'bar chart' request must not fabricate an HR chart.

        search_employees is patched to succeed, so this fails loudly if the
        old 'default to hr_headcount' behaviour ever comes back.
        """
        with patch("modules.hr.search_employees",
                   return_value={"status": "OK", "employees": [
                       {"department": "IT"}, {"department": "Finance"},
                   ]}):
            self.assertIsNone(_hardcoded_generate("show me in bar chart", None))


class TestEmployeeChartStillWorks(unittest.TestCase):
    """Removing the hr_headcount default must not break the per-employee charts."""

    _LEAVE = {
        "status": "OK", "employee_name": "Rahul Sharma",
        "annual_leave": {"entitled": 24, "used": 8, "balance": 16},
        "sick_leave":   {"entitled": 12, "used": 3, "balance": 9},
        "casual_leave": {"entitled": 6,  "used": 1, "balance": 5},
    }

    def test_leave_chart_for_employee_id(self):
        with patch("modules.hr.get_leave_balance", return_value=self._LEAVE):
            payload = _hardcoded_generate("leave balance for EMP001 chart", None)
        self.assertIsNotNone(payload)
        self.assertIn("EMP001", payload["title"])

    def test_leave_chart_when_query_has_only_the_id(self):
        """"EMP001 as a bar chart" names no HR keyword — the ID must pin it."""
        with patch("modules.hr.get_leave_balance", return_value=self._LEAVE):
            payload = _hardcoded_generate("EMP001 as a bar chart", None)
        self.assertIsNotNone(payload)
        self.assertIn("EMP001", payload["title"])

    def test_customer_chart_when_query_has_only_the_id(self):
        with patch("modules.sd.get_customer_orders", return_value=_FAKE_ORDERS), \
             patch("modules.sd.get_customer_info",   return_value=_FAKE_CUSTOMER):
            payload = _hardcoded_generate("C001 as a bar chart", None)
        self.assertIsNotNone(payload)
        self.assertIn("C001", payload["title"])

    def test_id_pinned_source_is_still_rbac_checked(self):
        """An ID must not bypass the module allow-list."""
        payload = _hardcoded_generate("EMP001 as a bar chart",
                                      allowed_tools={"get_customer_info"})
        self.assertIs(payload, ACCESS_DENIED)
        payload = _hardcoded_generate("C001 as a bar chart",
                                      allowed_tools={"get_leave_balance"})
        self.assertIs(payload, ACCESS_DENIED)


class TestCustomerChartRbac(unittest.TestCase):

    def test_customer_chart_denied_without_sd_tools(self):
        payload = _hardcoded_generate(
            "Get customer info for C001 and show me in bar chart",
            allowed_tools={"get_leave_balance", "search_employees"})
        self.assertIs(payload, ACCESS_DENIED)

    def test_customer_chart_allowed_with_sd_tools(self):
        with patch("modules.sd.get_customer_orders", return_value=_FAKE_ORDERS), \
             patch("modules.sd.get_customer_info",   return_value=_FAKE_CUSTOMER):
            payload = _hardcoded_generate(
                "Get customer info for C001 and show me in bar chart",
                allowed_tools={"get_customer_info", "get_customer_orders"})
        self.assertIsNotNone(payload)
        self.assertIsNot(payload, ACCESS_DENIED)
        self.assertIn("C001", payload["title"])


class TestPlannerToolScope(unittest.TestCase):
    """The planner prompt used to carry all 46 tools — ~7.7k tokens, which
    overflowed the local model's context and produced unusable plans."""

    def test_every_report_tool_exists_in_the_registry(self):
        from tools.tool_registry import TOOLS
        unknown = _REPORT_TOOLS - {t["name"] for t in TOOLS}
        self.assertEqual(set(), unknown, f"stale tool names: {unknown}")

    def test_report_tools_cover_every_reporting_module(self):
        from tools.tool_registry import TOOLS
        mods = {t["module"] for t in TOOLS if t["name"] in _REPORT_TOOLS}
        self.assertEqual({"FI/CO", "MM", "SD", "HR", "PP"}, mods)

    def test_scoped_prompt_is_far_smaller_than_the_full_registry(self):
        from tools.tool_registry import get_tools_for_prompt
        full   = len(get_tools_for_prompt())
        scoped = len(get_tools_for_prompt(set(_REPORT_TOOLS)))
        self.assertLess(scoped, full / 3)

    def test_planner_sees_only_tools_the_caller_may_run(self):
        """The planner must not plan a step execution would reject."""
        from agent.report_agent import LLMReportAgent
        agent = LLMReportAgent.__new__(LLMReportAgent)
        agent._call_llm = lambda *a, **k: "{}"
        captured = {}
        import tools.tool_registry as reg
        real = reg.get_tools_for_prompt
        def spy(allowed=None):
            captured["scope"] = allowed
            return real(allowed)
        reg.get_tools_for_prompt = spy
        try:
            agent._plan("headcount chart", allowed_tools={"search_employees", "get_payslip",
                                                          "create_sales_order"})
        finally:
            reg.get_tools_for_prompt = real
        self.assertEqual({"search_employees", "get_payslip"}, captured["scope"])

    def test_planner_declines_when_caller_has_no_report_tools(self):
        from agent.report_agent import LLMReportAgent
        agent = LLMReportAgent.__new__(LLMReportAgent)
        agent._call_llm = lambda *a, **k: self.fail("LLM must not be called")
        self.assertIsNone(agent._plan("headcount chart", allowed_tools={"create_sales_order"}))


class TestLlmPayloadValidation(unittest.TestCase):
    """A 3B model returned a customer master record as 13 chart points whose
    values were strings like "Mumbai". None of that may reach the widget."""

    def test_rejects_non_numeric_values(self):
        bad = {"chart_type": "bar", "title": "Customer Info", "data": [
            {"label": "name", "value": "Mahindra & Mahindra Ltd"},
            {"label": "city", "value": "Mumbai"},
            {"label": "country", "value": "India"},
        ]}
        self.assertIsNone(_validated_payload(bad))

    def test_rejects_a_single_point_chart(self):
        one = {"chart_type": "bar", "title": "x", "data": [
            {"label": "credit_limit", "value": 50000000},
            {"label": "city", "value": "Mumbai"},
        ]}
        self.assertIsNone(_validated_payload(one))

    def test_keeps_numeric_points_and_drops_the_rest(self):
        mixed = {"chart_type": "bar", "title": "x", "data": [
            {"label": "SO5001", "value": 14000000},
            {"label": "city",   "value": "Mumbai"},
            {"label": "SO5011", "value": "630000"},
        ]}
        out = _validated_payload(mixed)
        self.assertIsNotNone(out)
        self.assertEqual(["SO5001", "SO5011"], [d["label"] for d in out["data"]])
        self.assertEqual([14000000.0, 630000.0], [d["value"] for d in out["data"]])

    def test_rejects_unknown_chart_type(self):
        self.assertIsNone(_validated_payload({"chart_type": "sankey", "data": []}))

    def test_rejects_empty_table_and_pivot(self):
        self.assertIsNone(_validated_payload({"chart_type": "table", "columns": [], "rows": []}))
        self.assertIsNone(_validated_payload({"chart_type": "pivot", "rows": ["a"],
                                              "columns": ["b"], "values": []}))

    def test_booleans_are_not_numbers(self):
        payload = {"chart_type": "bar", "data": [
            {"label": "active", "value": True}, {"label": "closed", "value": False},
        ]}
        self.assertIsNone(_validated_payload(payload))


class TestDeterministicPathWins(unittest.TestCase):
    """SAP numbers must come from SAP rows, not from the model's imagination."""

    def test_known_query_never_reaches_the_llm(self):
        from agent.report_agent import LLMReportAgent
        agent = LLMReportAgent.__new__(LLMReportAgent)
        agent._llm_generate = lambda *a, **k: self.fail(
            "deterministic fetchers can serve this — the LLM must not be asked")
        with patch("modules.sd.get_customer_orders", return_value=_FAKE_ORDERS), \
             patch("modules.sd.get_customer_info",   return_value=_FAKE_CUSTOMER):
            payload = agent.generate("Get customer info for C001 bar chart", None)
        self.assertIn("C001", payload["title"])

    def test_access_denied_is_not_retried_via_the_llm(self):
        from agent.report_agent import LLMReportAgent
        agent = LLMReportAgent.__new__(LLMReportAgent)
        agent._llm_generate = lambda *a, **k: self.fail("RBAC denial must be final")
        payload = agent.generate("Get customer info for C001 bar chart",
                                 allowed_tools={"search_employees"})
        self.assertIs(payload, ACCESS_DENIED)

    def test_unknown_query_falls_through_to_the_llm(self):
        from agent.report_agent import LLMReportAgent
        agent = LLMReportAgent.__new__(LLMReportAgent)
        sentinel = {"chart_type": "bar", "title": "t",
                    "data": [{"label": "a", "value": 1}, {"label": "b", "value": 2}]}
        agent._llm_generate = lambda *a, **k: sentinel
        with patch("modules.hr.search_employees",
                   return_value={"status": "OK", "employees": [{"department": "IT"}]}):
            self.assertIs(sentinel, agent.generate("show me in bar chart", None))


class TestDeterministicAggregation(unittest.TestCase):
    """The LLM plans; Python computes. No chart number may originate in the model."""

    EMPLOYEES = {"e": {"status": "OK", "employees": [
        {"employee_id": "EMP001", "department": "IT",      "salary": 90000},
        {"employee_id": "EMP002", "department": "IT",      "salary": 70000},
        {"employee_id": "EMP003", "department": "Finance", "salary": 80000},
    ]}}
    ORDERS = {"o": {"status": "OK", "orders": [
        {"order_id": "SO1", "value": 14000000.0},
        {"order_id": "SO2", "value": 630000.0},
    ]}}

    def test_count_groups_rows(self):
        out = _aggregate(self.EMPLOYEES,
                         {"group_by": "department", "metric": "count",
                          "value_field": None, "label_field": "department"},
                         "bar", "Headcount")
        self.assertEqual([("IT", 2.0), ("Finance", 1.0)],
                         [(d["label"], d["value"]) for d in out["data"]])

    def test_sum_uses_the_named_value_field(self):
        out = _aggregate(self.EMPLOYEES,
                         {"group_by": "department", "metric": "sum",
                          "value_field": "salary", "label_field": "department"},
                         "bar", "Payroll")
        self.assertEqual([("IT", 160000.0), ("Finance", 80000.0)],
                         [(d["label"], d["value"]) for d in out["data"]])

    def test_avg_uses_the_named_value_field(self):
        out = _aggregate(self.EMPLOYEES,
                         {"group_by": "department", "metric": "avg",
                          "value_field": "salary", "label_field": "department"},
                         "bar", "Avg salary")
        by = {d["label"]: d["value"] for d in out["data"]}
        self.assertEqual(80000.0, by["IT"])
        self.assertEqual(80000.0, by["Finance"])

    def test_value_metric_emits_one_point_per_row(self):
        out = _aggregate(self.ORDERS,
                         {"group_by": None, "metric": "value",
                          "value_field": "value", "label_field": "order_id"},
                         "bar", "Orders")
        self.assertEqual([("SO1", 14000000.0), ("SO2", 630000.0)],
                         [(d["label"], d["value"]) for d in out["data"]])

    def test_percentages_sum_to_100(self):
        out = _aggregate(self.EMPLOYEES,
                         {"group_by": "department", "metric": "count",
                          "value_field": None, "label_field": "department"},
                         "pie", "Headcount")
        self.assertAlmostEqual(100.0, sum(d["pct"] for d in out["data"]), places=1)

    def test_every_value_traces_to_a_source_row(self):
        """The guarantee: no number appears that the SAP rows do not support."""
        out = _aggregate(self.ORDERS,
                         {"group_by": None, "metric": "value",
                          "value_field": "value", "label_field": "order_id"},
                         "bar", "Orders")
        source = {r["value"] for r in self.ORDERS["o"]["orders"]}
        self.assertTrue({d["value"] for d in out["data"]} <= source)

    def test_recovers_when_the_planned_value_field_is_absent(self):
        """A wrong field name in the plan falls back to a real numeric column.

        The recovered values still come from the SAP rows — inference picks
        which column to read, never what the number is.
        """
        out = _aggregate(self.ORDERS,
                         {"group_by": None, "metric": "sum",
                          "value_field": "nonexistent",
                          "label_field": "order_id"}, "bar", "x")
        self.assertIsNotNone(out)
        source = {r["value"] for r in self.ORDERS["o"]["orders"]}
        self.assertTrue({d["value"] for d in out["data"]} <= source)

    def test_declines_when_the_rows_carry_no_numeric_column(self):
        text_only = {"t": {"status": "OK", "items": [
            {"code": "A", "note": "alpha"}, {"code": "B", "note": "beta"},
            {"code": "C", "note": "gamma"},
        ]}}
        self.assertIsNone(_aggregate(text_only,
                                     {"group_by": None, "metric": "sum",
                                      "value_field": "amount",
                                      "label_field": "code"}, "bar", "x"))

    def test_declines_when_no_tool_returned_rows(self):
        self.assertIsNone(_aggregate({"a": {"status": "OK", "total": 5}},
                                     {"group_by": None, "metric": "count",
                                      "value_field": None, "label_field": "x"},
                                     "bar", "x"))

    def test_declines_on_failed_tool_results(self):
        self.assertIsNone(_aggregate({"a": {"status": "ERROR", "message": "denied"}},
                                     {"group_by": "d", "metric": "count",
                                      "value_field": None, "label_field": "d"},
                                     "bar", "x"))

    def test_picks_the_richest_collection_across_tools(self):
        collected = {**self.ORDERS, **self.EMPLOYEES}
        out = _aggregate(collected,
                         {"group_by": "department", "metric": "count",
                          "value_field": None, "label_field": "department"},
                         "bar", "Headcount")
        self.assertEqual({"IT", "Finance"}, {d["label"] for d in out["data"]})

    def test_carries_the_planned_title_and_chart_type(self):
        out = _aggregate(self.ORDERS,
                         {"group_by": None, "metric": "value",
                          "value_field": "value", "label_field": "order_id"},
                         "pie", "Sales Orders by Value")
        self.assertEqual("pie", out["chart_type"])
        self.assertEqual("Sales Orders by Value", out["title"])


class TestAggregationEdgeCases(unittest.TestCase):
    """Shapes the real SAP rows and the real model output actually produce."""

    def test_decimal_money_columns_are_numeric(self):
        """Every money column in this schema is DECIMAL, not float."""
        collected = {"i": {"status": "OK", "open_invoices": [
            {"vendor_name": "Acme", "amount": Decimal("3600000.00")},
            {"vendor_name": "Globex", "amount": Decimal("1400000.00")},
        ]}}
        out = _aggregate(collected, {"group_by": "vendor_name", "metric": "sum",
                                     "value_field": "amount",
                                     "label_field": "vendor_name"}, "bar", "Outstanding")
        self.assertIsNotNone(out, "Decimal amounts were dropped as non-numeric")
        self.assertEqual([("Acme", 3600000.0), ("Globex", 1400000.0)],
                         [(d["label"], d["value"]) for d in out["data"]])

    def test_validator_accepts_decimal_values(self):
        payload = {"chart_type": "bar", "data": [
            {"label": "a", "value": Decimal("10.5")},
            {"label": "b", "value": Decimal("2")},
        ]}
        out = _validated_payload(payload)
        self.assertIsNotNone(out)
        self.assertEqual([10.5, 2.0], [d["value"] for d in out["data"]])

    def test_string_null_in_the_plan_is_treated_as_unset(self):
        """Small models write the string "null", not JSON null."""
        collected = {"e": {"status": "OK", "employees": [
            {"department": "IT"}, {"department": "IT"}, {"department": "HR"},
        ]}}
        out = _aggregate(collected, {"group_by": "department", "metric": "null",
                                     "value_field": "null",
                                     "label_field": "department"}, "bar", "Headcount")
        self.assertIsNotNone(out)
        self.assertEqual([("IT", 2.0), ("HR", 1.0)],
                         [(d["label"], d["value"]) for d in out["data"]])

    def test_declines_a_uniform_count_chart(self):
        """Counting 15 unique cost centres gives 15 identical bars."""
        collected = {"c": {"status": "OK", "cost_centers": [
            {"cost_center": f"CC{i}"} for i in range(6)
        ]}}
        self.assertIsNone(_aggregate(collected,
                                     {"group_by": "cost_center", "metric": "count",
                                      "value_field": None,
                                      "label_field": "cost_center"}, "pie", "Cost Centres"))

    def test_two_equal_counts_are_still_a_valid_chart(self):
        collected = {"e": {"status": "OK", "employees": [
            {"department": "IT"}, {"department": "HR"},
        ]}}
        self.assertIsNotNone(_aggregate(collected,
                                        {"group_by": "department", "metric": "count",
                                         "value_field": None,
                                         "label_field": "department"}, "bar", "Headcount"))


class TestPlannerParameterSanitising(unittest.TestCase):
    """The planner invents filters the user never asked for.

    Asked to chart vendors by outstanding it called
    get_open_invoices(vendor_id="V001") — one invoice, which cannot be charted,
    so the request produced no chart at all. A value that appears nowhere in
    the user's query is the model's invention, not the user's intent.
    """

    def test_drops_an_invented_optional_filter(self):
        self.assertEqual(
            {}, _sanitize_parameters("get_open_invoices", {"vendor_id": "V001"},
                                     "chart vendors by outstanding"))

    def test_keeps_a_filter_the_user_actually_named(self):
        self.assertEqual(
            {"vendor_id": "V001"},
            _sanitize_parameters("get_open_invoices", {"vendor_id": "V001"},
                                 "chart open invoices for V001"))

    def test_keeps_required_parameters_even_when_unmatched(self):
        """Dropping a required argument would just break the call."""
        self.assertEqual(
            {"customer_id": "C001"},
            _sanitize_parameters("get_customer_orders", {"customer_id": "C001"},
                                 "chart that customer's orders"))

    def test_matching_is_case_insensitive(self):
        self.assertEqual(
            {"vendor_id": "V001"},
            _sanitize_parameters("get_open_invoices", {"vendor_id": "V001"},
                                 "invoices for vendor v001 as a bar chart"))

    def test_drops_null_valued_parameters(self):
        self.assertEqual(
            {}, _sanitize_parameters("get_open_invoices", {"vendor_id": "null"},
                                     "chart vendors by outstanding"))

    def test_empty_and_missing_parameters_are_safe(self):
        self.assertEqual({}, _sanitize_parameters("list_open_sales_orders", {}, "q"))
        self.assertEqual({}, _sanitize_parameters("list_open_sales_orders", None, "q"))

    def test_unknown_tool_keeps_parameters_untouched(self):
        """Never silently strip arguments for a tool whose schema we cannot read."""
        params = {"whatever": "xyz"}
        self.assertEqual(params, _sanitize_parameters("not_a_tool", params, "q"))

    def test_sanitising_collapses_duplicate_planned_calls(self):
        """Two invented filters on the same tool become one identical call."""
        a = _sanitize_parameters("get_open_invoices", {"vendor_id": "V001"}, "vendors chart")
        b = _sanitize_parameters("get_open_invoices", {"vendor_id": "V002"}, "vendors chart")
        self.assertEqual(a, b)


class TestPlannedTitleSanitising(unittest.TestCase):
    """An invented filter also lands in the title.

    After the filter is dropped the chart covers every vendor, so a title
    reading "Outstanding Vendors by Value - V001" describes data the chart
    does not show.
    """

    def test_strips_an_entity_id_the_user_never_mentioned(self):
        self.assertEqual(
            "Outstanding Vendors by Value",
            _sanitize_title("Outstanding Vendors by Value \u2014 V001",
                            "chart vendors by outstanding"))

    def test_keeps_an_entity_id_the_user_asked_for(self):
        title = "Sales Orders by Value \u2014 C001"
        self.assertEqual(title, _sanitize_title(title, "customer C001 as a bar chart"))

    def test_strips_a_parenthesised_invented_id(self):
        self.assertEqual(
            "Leave Balance",
            _sanitize_title("Leave Balance (EMP007)", "chart the leave balances"))

    def test_leaves_an_id_free_title_alone(self):
        title = "Active Headcount by Department"
        self.assertEqual(title, _sanitize_title(title, "headcount by department"))

    def test_never_returns_an_empty_title(self):
        self.assertEqual("V001", _sanitize_title("V001", "chart vendors"))

    def test_tidies_trailing_separators_and_whitespace(self):
        self.assertEqual("Open Invoices",
                         _sanitize_title("Open Invoices \u2014  V001  ", "invoice chart"))
        self.assertEqual("Open Invoices",
                         _sanitize_title("Open Invoices - V001", "invoice chart"))
        self.assertEqual("Open Invoices",
                         _sanitize_title("Open Invoices: V001", "invoice chart"))


# \u2500\u2500 Anaphoric follow-ups ("this bar chart") \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
class TestConversationContext(unittest.TestCase):
    """A follow-up chart request names its subject only in the previous turn.

    "i need this bar chart" carries no data keyword at all, so the bare-message
    detectors decline and the request used to fall through to freeform chat \u2014
    where the model answered with matplotlib code instead of a chart.
    """

    def test_bare_followup_resolves_subject_from_previous_turn(self):
        context = [
            {"role": "user", "content": "show me the open invoices"},
            {"role": "assistant", "content": "There are 4 open vendor invoices totalling INR 1,20,000."},
        ]
        self.assertEqual(
            _detect_data_source("i need this bar chart", context),
            "fi_co_invoices",
        )

    def test_context_does_not_override_a_subject_in_the_message(self):
        """An explicit subject wins; context only fills a gap."""
        context = [
            {"role": "user", "content": "show me the open invoices"},
            {"role": "assistant", "content": "There are 4 open vendor invoices."},
        ]
        self.assertEqual(
            _detect_data_source("headcount by department as a bar chart", context),
            "hr_headcount",
        )

    def test_still_declines_when_context_names_no_data_either(self):
        """Context must widen resolution, never manufacture a default."""
        context = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "Hello \u2014 how can I help with SAP today?"},
        ]
        self.assertIsNone(_detect_data_source("i need this bar chart", context))

    def test_absent_context_behaves_exactly_as_before(self):
        self.assertIsNone(_detect_data_source("i need this bar chart"))
        self.assertIsNone(_detect_data_source("i need this bar chart", None))
        self.assertIsNone(_detect_data_source("i need this bar chart", []))

    def test_only_recent_turns_are_consulted(self):
        """A stale subject many turns back must not hijack a fresh request."""
        context = [
            {"role": "user", "content": "show me the open invoices"},
            {"role": "assistant", "content": "There are 4 open vendor invoices."},
        ] + [
            {"role": "user", "content": "thanks"},
            {"role": "assistant", "content": "You are welcome."},
        ] * 6
        self.assertIsNone(_detect_data_source("i need this bar chart", context))

    _INVOICES = {
        "status": "OK",
        "open_invoices": [
            {"vendor_name": "Acme Ltd",  "amount": Decimal("1000")},
            {"vendor_name": "Globex SE", "amount": Decimal("2500")},
        ],
    }

    def test_hardcoded_generate_charts_the_referenced_subject(self):
        """The end-to-end fix: the message that produced matplotlib now charts."""
        context = [
            {"role": "user", "content": "list the open invoices"},
            {"role": "assistant", "content": "4 open vendor invoices are outstanding."},
        ]
        with patch("modules.fi_co.get_open_invoices", return_value=self._INVOICES):
            payload = _hardcoded_generate("i need this bar chart", None, context)
        self.assertIsNotNone(payload)
        self.assertEqual(payload["chart_type"], "bar")
        self.assertEqual([d["label"] for d in payload["data"]],
                         ["Globex SE", "Acme Ltd"])

    def test_same_message_without_context_still_declines(self):
        """Guards the fix: resolution must come from context, not a new default."""
        with patch("modules.fi_co.get_open_invoices", return_value=self._INVOICES):
            self.assertIsNone(_hardcoded_generate("i need this bar chart", None))


# \u2500\u2500 Fallthrough guard \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
class TestExplicitChartRequest(unittest.TestCase):
    """Only an unambiguous chart ask may block the fallthrough to chat.

    is_report_query() fires on loose words like "compare", which are ordinary
    conversation. Blocking those would answer a real question with a "which
    chart?" prompt, so the guard uses a narrower test.
    """

    def test_explicit_chart_asks_are_caught(self):
        for q in ("i need this bar chart",
                  "show me a pie chart",
                  "give me a graph of that",
                  "can i get this as a chart",
                  "plot this as a histogram"):
            self.assertTrue(is_explicit_chart_request(q), q)

    def test_loose_report_words_are_not_treated_as_chart_asks(self):
        for q in ("compare vendor V001 and V002",
                  "what is the share of open orders",
                  "show me the comparison of last month",
                  "get customer info for C001"):
            self.assertFalse(is_explicit_chart_request(q), q)

    def test_loose_words_still_route_through_is_report_query(self):
        """The guard narrows; it must not change existing routing."""
        self.assertTrue(is_report_query("compare vendor V001 and V002"))

    def test_clarify_text_names_chartable_data_and_no_code(self):
        text = clarify_text("i need this bar chart")
        self.assertIn("bar chart", text.lower())
        for banned in ("matplotlib", "import ", "plt.", "```"):
            self.assertNotIn(banned, text.lower())
        # It must actually tell the user what can be charted.
        self.assertTrue(any(w in text.lower()
                            for w in ("invoice", "headcount", "stock", "order")))


if __name__ == "__main__":
    unittest.main()
