"""
Quick smoke tests for SAPAgent tool routing.
Tests the keyword fallback router and tool extraction — no Ollama required.
"""
import sys
import json

# ── patch out the LLM so tests run without Ollama ────────────────────────────
import unittest
from unittest.mock import patch, MagicMock

# Prevent real HTTP calls during import
with patch("requests.get", return_value=MagicMock(status_code=404)):
    from agent.sap_agent import SAPAgent

def make_agent():
    with patch("requests.get", return_value=MagicMock(status_code=404)):
        agent = SAPAgent()
    agent._use_mlx = False
    return agent


# ── Keyword fallback router tests ─────────────────────────────────────────────
class TestInferToolFromQuery(unittest.TestCase):

    def setUp(self):
        self.agent = make_agent()
        self.infer = self.agent._infer_tool_from_query

    def _check(self, query, expected_tool, expected_params=None):
        result = self.infer(query)
        self.assertIsNotNone(result, f"No tool inferred for: {query!r}")
        self.assertEqual(result["name"], expected_tool,
                         f"Query {query!r}: expected {expected_tool}, got {result['name']}")
        if expected_params:
            for k, v in expected_params.items():
                self.assertEqual(result["parameters"].get(k), v,
                                 f"Param {k!r} mismatch for query {query!r}")

    def test_abap_program(self):
        self._check("show me ABAP program ZREP_VENDOR_LIST",
                    "get_abap_program", {"program_name": "ZREP_VENDOR_LIST"})

    def test_abap_program_no_keyword(self):
        self._check("get program ZVENDOR_REPORT",
                    "get_abap_program", {"program_name": "ZVENDOR_REPORT"})

    def test_vendor(self):
        self._check("show vendor V001", "get_vendor_info", {"vendor_id": "V001"})

    def test_invoice(self):
        self._check("status of invoice INV1002", "get_invoice_status", {"invoice_id": "INV1002"})

    def test_cost_center(self):
        self._check("budget for CC200", "get_cost_center_budget", {"cost_center_id": "CC200"})

    def test_purchase_order(self):
        self._check("details of PO2001", "get_purchase_order", {"po_id": "PO2001"})

    def test_sales_order(self):
        self._check("get sales order SO5001", "get_sales_order", {"order_id": "SO5001"})

    def test_production_order(self):
        self._check("show production order PRD7001", "get_production_order", {"order_id": "PRD7001"})

    def test_employee_info(self):
        self._check("info on employee EMP003", "get_employee_info", {"emp_id": "EMP003"})

    def test_leave_balance(self):
        self._check("leave balance for EMP001", "get_leave_balance", {"emp_id": "EMP001"})

    def test_payslip(self):
        self._check("show payslip for EMP002", "get_payslip", {"emp_id": "EMP002"})

    def test_material_info(self):
        self._check("material details MAT001", "get_material_info", {"material_id": "MAT001"})

    def test_stock_level(self):
        self._check("stock level for MAT003", "get_stock_level", {"material_id": "MAT003"})

    def test_open_invoices(self):
        self._check("show all open invoices", "get_open_invoices")

    def test_list_cost_centers(self):
        self._check("list all cost centers", "list_all_cost_centers")

    def test_reorder(self):
        self._check("which materials need reorder?", "check_reorder_needed")

    def test_no_match_general(self):
        result = self.infer("hello, how are you?")
        self.assertIsNone(result)

    def test_no_match_sap_general(self):
        result = self.infer("what is SAP?")
        self.assertIsNone(result)


# ── Tool extraction from LLM output tests ─────────────────────────────────────
class TestExtractToolCall(unittest.TestCase):

    def setUp(self):
        self.agent = make_agent()

    def test_clean_json(self):
        response = '{"tool_call": {"name": "get_vendor_info", "parameters": {"vendor_id": "V001"}}}'
        result = self.agent._extract_tool_call(response)
        self.assertIsNotNone(result)
        self.assertEqual(result["name"], "get_vendor_info")

    def test_json_in_markdown(self):
        response = '```json\n{"tool_call": {"name": "get_stock_level", "parameters": {"material_id": "MAT001"}}}\n```'
        result = self.agent._extract_tool_call(response)
        self.assertIsNotNone(result)
        self.assertEqual(result["name"], "get_stock_level")

    def test_json_embedded_in_text(self):
        response = 'Sure! {"tool_call": {"name": "get_invoice_status", "parameters": {"invoice_id": "INV1000"}}} here you go'
        result = self.agent._extract_tool_call(response)
        self.assertIsNotNone(result)
        self.assertEqual(result["name"], "get_invoice_status")

    def test_hallucinated_tool_name_rejected(self):
        response = '{"tool_call": {"name": "tool_call", "parameters": {}}}'
        tool_call = self.agent._extract_tool_call(response)
        valid = tool_call and self.agent._is_valid_tool_call(tool_call)
        self.assertFalse(valid)

    def test_no_json(self):
        response = "I can help you with SAP queries. What would you like to know?"
        result = self.agent._extract_tool_call(response)
        self.assertIsNone(result)


# ── Tool execution tests (uses mock data, no SAP connection needed) ────────────
class TestToolExecution(unittest.TestCase):

    def setUp(self):
        self.agent = make_agent()

    def test_get_vendor_info_found(self):
        from tools.tool_registry import execute_tool
        result = execute_tool("get_vendor_info", {"vendor_id": "V001"})
        self.assertEqual(result["status"], "OK")
        self.assertIn("name", result)

    def test_get_vendor_info_not_found(self):
        from tools.tool_registry import execute_tool
        result = execute_tool("get_vendor_info", {"vendor_id": "V999"})
        self.assertEqual(result["status"], "ERROR")

    def test_unknown_tool(self):
        from tools.tool_registry import execute_tool
        result = execute_tool("tool_call", {})
        self.assertEqual(result["status"], "ERROR")
        self.assertIn("Unknown tool", result["message"])

    def test_get_abap_program_found(self):
        from tools.tool_registry import execute_tool
        result = execute_tool("get_abap_program", {"program_name": "ZREP_VENDOR_LIST"})
        self.assertEqual(result["status"], "OK")
        self.assertIn("description", result)

    def test_sap_source_injected(self):
        from tools.tool_registry import execute_tool
        result = execute_tool("get_vendor_info", {"vendor_id": "V001"})
        if result["status"] == "OK":
            self.assertIn("sap_source", result)
            self.assertIn("bapi", result["sap_source"])
            self.assertIn("tcode", result["sap_source"])


if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(TestInferToolFromQuery))
    suite.addTests(loader.loadTestsFromTestCase(TestExtractToolCall))
    suite.addTests(loader.loadTestsFromTestCase(TestToolExecution))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
