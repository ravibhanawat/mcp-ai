"""
Regression tests for the defects found in the end-to-end QA cycle.

One test (or small group) per finding, named with the finding id so a failure
points straight at the report entry. Every test is hermetic: no live
PostgreSQL, no live Ollama, no network.

Run:
    APP_ENV=development python -m pytest tests/test_qa_findings.py -q
"""
from __future__ import annotations

import asyncio
import datetime
import json
import os
import sys
import time
import unittest
import uuid
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ["APP_ENV"] = "development"
os.environ["DISABLE_AUTH"] = "false"
os.environ["JWT_SECRET_KEY"] = "test-access-secret-do-not-use-in-prod"
os.environ["JWT_REFRESH_SECRET"] = "test-refresh-secret-do-not-use-in-prod"
os.environ["CORS_ORIGINS"] = "http://localhost:5173"
os.environ["OPENAI_API_KEY"] = ""
os.environ["ANTHROPIC_API_KEY"] = ""

from fastapi.testclient import TestClient  # noqa: E402

import api.server as server                # noqa: E402
from auth import users as user_store        # noqa: E402


def _client_as(roles, user_id="tester"):
    """TestClient with auth pinned to a caller of the given roles."""
    server.app.dependency_overrides[server.get_current_user] = lambda: {
        "user_id": user_id, "roles": roles
    }
    if "admin" in roles:
        server.app.dependency_overrides[server.require_admin] = lambda: {
            "user_id": user_id, "roles": roles
        }
    else:
        def _deny():
            from fastapi import HTTPException
            raise HTTPException(status_code=403, detail="Admin role required.")
        server.app.dependency_overrides[server.require_admin] = _deny
    return TestClient(server.app)


class _OverrideCleanup(unittest.TestCase):
    """dependency_overrides lives on the one process-global app object."""

    def tearDown(self):
        server.app.dependency_overrides.clear()


# ── C-2 ───────────────────────────────────────────────────────────────────────

class TestC2AuditEncoder(unittest.TestCase):
    """A SAP record carrying a date must not be able to fail the request."""

    def test_log_request_accepts_a_date_in_tool_parameters(self):
        from core.audit_logger import log_request
        rid = log_request(
            user_id="u", user_roles=["fi_co_analyst"], client_ip="1.2.3.4",
            endpoint="/chat", query="q", tool_called="get_vendor_info",
            tool_parameters={"vendor_id": "V001", "created_on": datetime.date(2026, 1, 15)},
            sap_source=None, response_text="ok", duration_ms=1, status="ok",
        )
        self.assertTrue(rid)

    def test_safe_encoder_handles_every_type_the_db_returns(self):
        from core.audit_logger import _SafeEncoder
        payload = {
            "d": datetime.date(2026, 1, 15),
            "dt": datetime.datetime(2026, 1, 15, 9, 30, 0),
            "t": datetime.time(9, 30),
            "td": datetime.timedelta(days=2),
            "dec": Decimal("10.50"),
            "uid": uuid.UUID("11111111-1111-1111-1111-111111111111"),
        }
        decoded = json.loads(json.dumps(payload, cls=_SafeEncoder))
        self.assertEqual("2026-01-15", decoded["d"])
        self.assertEqual(10.5, decoded["dec"])
        self.assertEqual("11111111-1111-1111-1111-111111111111", decoded["uid"])

    def test_an_unserializable_value_still_does_not_raise(self):
        """Defence in depth: the encoder cannot know every type in advance."""
        from core.audit_logger import log_request

        class Exotic:
            pass

        rid = log_request(
            user_id="u", user_roles=[], client_ip="1.2.3.4", endpoint="/chat",
            query="q", tool_called="t", tool_parameters={"x": Exotic()},
            sap_source=None, response_text="ok", duration_ms=1, status="ok",
        )
        self.assertTrue(rid)

    def test_a_disk_failure_does_not_propagate_to_the_caller(self):
        from core import audit_logger
        with patch("builtins.open", side_effect=OSError("disk full")):
            rid = audit_logger.log_request(
                user_id="u", user_roles=[], client_ip="1.2.3.4",
                endpoint="/chat", query="q", tool_called=None,
                tool_parameters=None, sap_source=None, response_text="ok",
                duration_ms=1, status="ok",
            )
        self.assertTrue(rid)


# ── C-1 ───────────────────────────────────────────────────────────────────────

class TestC1ActivityMiddlewareDoesNotBlockTheLoop(_OverrideCleanup):

    def test_a_slow_activity_write_does_not_serialize_requests(self):
        """Two concurrent requests must overlap, not queue behind the log write.

        The activity write is made to take 0.4 s. Run on the event loop, four
        requests cost ~1.6 s; run off it, they overlap and cost ~0.4 s.
        """
        from httpx import ASGITransport, AsyncClient

        def _slow_write(**kwargs):
            time.sleep(0.4)

        async def _run():
            transport = ASGITransport(app=server.app)
            async with AsyncClient(transport=transport, base_url="http://t") as ac:
                started = time.monotonic()
                await asyncio.gather(*(ac.get("/") for _ in range(4)))
                return time.monotonic() - started

        with patch.object(server, "_ACTIVITY_DB", True), \
             patch.object(server, "_write_activity", _slow_write):
            elapsed = asyncio.run(_run())

        self.assertLess(
            elapsed, 1.2,
            f"4 concurrent requests took {elapsed:.2f}s — the 0.4s activity "
            f"write is blocking the event loop instead of running in a thread.",
        )

    def test_connection_pool_has_an_explicit_bounded_timeout(self):
        """The 30s psycopg default is far too patient for a request path."""
        import db.connection as dbc
        with patch.object(dbc, "_pool", None), \
             patch("db.connection.ConnectionPool") as fake_pool:
            dbc._get_pool()
        kwargs = fake_pool.call_args.kwargs
        self.assertIn("timeout", kwargs)
        self.assertLessEqual(kwargs["timeout"], 5)


class TestC1KnownDownDatabaseFailsFast(unittest.TestCase):
    """A bounded timeout still costs every caller that timeout, every time.

    With the database down, each request paid the full pool timeout again —
    /health took 12 s because it pays it more than once. Once a connection has
    failed, the next callers should be told immediately rather than each
    rediscovering it.
    """

    def setUp(self):
        import db.connection as dbc
        dbc.reset_availability()

    tearDown = setUp

    def test_a_failure_is_remembered_and_the_next_call_does_not_retry(self):
        import db.connection as dbc
        attempts = []

        def _boom():
            attempts.append(1)
            raise dbc.psycopg.OperationalError("connection refused")

        with patch.object(dbc, "_get_pool", side_effect=_boom):
            with self.assertRaises(Exception):
                dbc.query_one("SELECT 1")
            self.assertEqual(1, len(attempts))

            started = time.monotonic()
            with self.assertRaises(dbc.DatabaseUnavailable):
                dbc.query_one("SELECT 1")
            elapsed = time.monotonic() - started

        self.assertEqual(1, len(attempts), "the second call retried a known-down database")
        self.assertLess(elapsed, 0.05)

    def test_is_connected_is_immediate_while_the_circuit_is_open(self):
        import db.connection as dbc
        dbc.note_unavailable(RuntimeError("down"))
        started = time.monotonic()
        self.assertFalse(dbc.is_connected())
        self.assertLess(time.monotonic() - started, 0.05)

    def test_the_circuit_closes_again_after_the_cooldown(self):
        import db.connection as dbc
        dbc.note_unavailable(RuntimeError("down"))
        self.assertTrue(dbc.circuit_open())
        with patch.object(dbc, "_unavailable_until", time.monotonic() - 1):
            self.assertFalse(dbc.circuit_open())

    def test_a_success_closes_the_circuit_immediately(self):
        import db.connection as dbc
        dbc.note_unavailable(RuntimeError("down"))
        dbc.note_available()
        self.assertFalse(dbc.circuit_open())


# ── H-1 ───────────────────────────────────────────────────────────────────────

class TestH1HealthChecksTheModelNotJustTheProvider(unittest.TestCase):

    @staticmethod
    def _resolved(identifier):
        return SimpleNamespace(
            model=SimpleNamespace(model_identifier=identifier),
            provider=SimpleNamespace(id="p1", name="Local Ollama"),
        )

    def test_a_model_the_provider_does_not_offer_is_not_healthy(self):
        from ai import health
        from ai.types import HealthResult

        fake = SimpleNamespace(
            health_check=lambda: HealthResult("healthy", 10, None),
            list_models=lambda: ["gemma4:26b", "llama3.2:1b"],
        )
        with patch("ai.health.build_provider", return_value=fake):
            result = health.probe(self._resolved("kutty"), None)

        self.assertNotEqual(
            "healthy", result.status,
            "probe() reported a model the provider does not offer as healthy.",
        )
        self.assertIn("kutty", (result.error or ""))

    def test_a_model_the_provider_offers_is_healthy(self):
        from ai import health
        from ai.types import HealthResult

        fake = SimpleNamespace(
            health_check=lambda: HealthResult("healthy", 10, None),
            list_models=lambda: ["gemma4:26b", "llama3.2:1b"],
        )
        with patch("ai.health.build_provider", return_value=fake):
            result = health.probe(self._resolved("llama3.2:1b"), None)
        self.assertEqual("healthy", result.status)

    def test_a_provider_that_cannot_list_models_is_still_healthy(self):
        """Not every provider exposes a model list; absence is not evidence."""
        from ai import health
        from ai.types import HealthResult

        fake = SimpleNamespace(
            health_check=lambda: HealthResult("healthy", 10, None),
            list_models=lambda: [],
        )
        with patch("ai.health.build_provider", return_value=fake):
            result = health.probe(self._resolved("anything"), None)
        self.assertEqual("healthy", result.status)

    def test_an_unreachable_provider_is_reported_unreachable(self):
        from ai import health
        from ai.types import HealthResult

        fake = SimpleNamespace(
            health_check=lambda: HealthResult("unreachable", 0, "refused"),
            list_models=lambda: [],
        )
        with patch("ai.health.build_provider", return_value=fake):
            result = health.probe(self._resolved("x"), None)
        self.assertEqual("unreachable", result.status)


# ── H-6 ───────────────────────────────────────────────────────────────────────

class TestH6ExhaustedFallbackChainIsA503(_OverrideCleanup):
    """Every model failing is "the AI is down", not "the server is broken"."""

    def _agent_raising(self, exc):
        class _Agent:
            requested_model_id = None
            manager = SimpleNamespace(resolve_only=lambda **kw: SimpleNamespace(
                resolved=SimpleNamespace(model=SimpleNamespace(id="m-test"))))

            def chat(self, *a, **kw):
                raise exc
        return _Agent()

    def test_every_provider_failing_answers_503_not_500(self):
        from ai.errors import AuthFailed
        with patch.object(server, "_get_agent",
                          return_value=self._agent_raising(
                              AuthFailed("provider rejected the credential"))):
            resp = _client_as(["read_only"]).post(
                "/chat", json={"message": "hello", "session_id": "s"})
        self.assertEqual(503, resp.status_code, resp.text)

    def test_the_message_says_it_is_not_the_callers_fault(self):
        from ai.errors import ProviderUnavailable
        with patch.object(server, "_get_agent",
                          return_value=self._agent_raising(
                              ProviderUnavailable("connection refused"))):
            resp = _client_as(["read_only"]).post(
                "/chat", json={"message": "hello", "session_id": "s"})
        self.assertNotIn("internal error", resp.text.lower())
        self.assertIn("administrator", resp.text.lower())

    def test_no_provider_detail_leaks_to_the_caller(self):
        from ai.errors import AuthFailed
        leaky = AuthFailed("401 Unauthorized for url: https://api.openai.com/v1/chat")
        with patch.object(server, "_get_agent", return_value=self._agent_raising(leaky)):
            resp = _client_as(["read_only"]).post(
                "/chat", json={"message": "hello", "session_id": "s"})
        self.assertNotIn("api.openai.com", resp.text)

    def test_an_unexpected_error_is_still_a_500(self):
        """Only AI-layer failures are reclassified; real bugs stay 500."""
        with patch.object(server, "_get_agent",
                          return_value=self._agent_raising(ValueError("a real bug"))):
            resp = _client_as(["read_only"]).post(
                "/chat", json={"message": "hello", "session_id": "s"})
        self.assertEqual(500, resp.status_code, resp.text)


# ── H-2 ───────────────────────────────────────────────────────────────────────

class TestH2TestMcpIsNotAnSsrfGadget(_OverrideCleanup):

    def test_a_non_admin_cannot_reach_the_endpoint(self):
        resp = _client_as(["read_only"]).post(
            "/config/test-mcp",
            json={"name": "x", "url": "https://example.com", "transport": "sse"},
        )
        self.assertEqual(403, resp.status_code)

    def test_loopback_and_private_targets_are_refused(self):
        client = _client_as(["admin"])
        for url in (
            "http://127.0.0.1:8099/health",
            "http://localhost:11434/",
            "http://169.254.169.254/latest/meta-data/",
            "http://10.0.0.5/",
            "http://192.168.1.1/",
            "http://[::1]/",
        ):
            with self.subTest(url=url):
                resp = client.post(
                    "/config/test-mcp",
                    json={"name": "x", "url": url, "transport": "sse"},
                )
                self.assertEqual(400, resp.status_code, resp.text)

    def test_non_http_schemes_are_refused(self):
        client = _client_as(["admin"])
        for url in ("file:///etc/passwd", "gopher://x/", "javascript:alert(1)"):
            with self.subTest(url=url):
                resp = client.post(
                    "/config/test-mcp",
                    json={"name": "x", "url": url, "transport": "sse"},
                )
                self.assertEqual(400, resp.status_code, resp.text)

    def test_a_public_https_target_is_still_probed(self):
        import socket
        # Resolution is stubbed so the test needs no DNS and no network.
        public = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]
        with patch("socket.getaddrinfo", return_value=public), \
             patch("requests.head") as head:
            head.return_value = SimpleNamespace(status_code=200)
            resp = _client_as(["admin"]).post(
                "/config/test-mcp",
                json={"name": "x", "url": "https://example.com/sse", "transport": "sse"},
            )
        self.assertEqual(200, resp.status_code, resp.text)
        self.assertTrue(resp.json()["success"])
        self.assertFalse(head.call_args.kwargs.get("allow_redirects", False))


# ── H-3 ───────────────────────────────────────────────────────────────────────

class TestH3DeactivationRevokesLiveTokens(unittest.TestCase):

    def test_a_deactivated_users_existing_token_is_rejected(self):
        from auth.jwt_handler import create_token
        token = create_token("ghost", ["read_only"])
        with patch.object(user_store, "get_user",
                          return_value={"user_id": "ghost", "roles": ["read_only"],
                                        "active": False}):
            resp = TestClient(server.app).get(
                "/auth/me", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(401, resp.status_code, resp.text)

    def test_an_active_users_token_still_works(self):
        from auth.jwt_handler import create_token
        token = create_token("live", ["read_only"])
        with patch.object(user_store, "get_user",
                          return_value={"user_id": "live", "roles": ["read_only"],
                                        "active": True}):
            resp = TestClient(server.app).get(
                "/auth/me", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(200, resp.status_code, resp.text)

    def test_a_user_deleted_from_the_store_is_rejected(self):
        from auth.jwt_handler import create_token
        token = create_token("deleted", ["admin"])
        with patch.object(user_store, "get_user", return_value=None):
            resp = TestClient(server.app).get(
                "/auth/me", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(401, resp.status_code, resp.text)


# ── H-4 ───────────────────────────────────────────────────────────────────────

class TestH4RefreshRotationRetiresTheOldToken(unittest.TestCase):

    def setUp(self):
        self.account = {"user_id": "rot", "roles": ["read_only"], "active": True}
        self.jtis: list[str] = []

        def _set_jtis(uid, jtis):
            self.jtis[:] = list(jtis)

        self.patches = [
            patch.object(user_store, "get_user",
                         lambda uid: dict(self.account) if uid == "rot" else None),
            patch.object(user_store, "get_refresh_jtis", lambda uid: list(self.jtis)),
            patch.object(user_store, "set_refresh_jtis", _set_jtis),
        ]
        for p in self.patches:
            p.start()
        self.client = TestClient(server.app)

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def _login_refresh_token(self):
        from auth.jwt_handler import create_refresh_token, decode_refresh_token
        token = create_refresh_token("rot")
        self.jtis[:] = [decode_refresh_token(token)["jti"]]
        return token

    def test_a_rotated_refresh_token_cannot_be_reused(self):
        first = self._login_refresh_token()
        ok = self.client.post("/auth/refresh", json={"refresh_token": first})
        self.assertEqual(200, ok.status_code, ok.text)

        replay = self.client.post("/auth/refresh", json={"refresh_token": first})
        self.assertEqual(
            401, replay.status_code,
            "the superseded refresh token was still accepted",
        )

    def test_the_new_refresh_token_works(self):
        first = self._login_refresh_token()
        second = self.client.post(
            "/auth/refresh", json={"refresh_token": first}).json()["refresh_token"]
        again = self.client.post("/auth/refresh", json={"refresh_token": second})
        self.assertEqual(200, again.status_code, again.text)

    def test_replaying_a_retired_token_invalidates_the_whole_chain(self):
        """Reuse of a superseded token is the standard theft signal."""
        first = self._login_refresh_token()
        second = self.client.post(
            "/auth/refresh", json={"refresh_token": first}).json()["refresh_token"]
        self.client.post("/auth/refresh", json={"refresh_token": first})   # replay
        after = self.client.post("/auth/refresh", json={"refresh_token": second})
        self.assertEqual(401, after.status_code,
                         "the live token survived a detected replay")


# ── H-5 ───────────────────────────────────────────────────────────────────────

class TestH5FailedProviderCreateLeavesNothingBehind(_OverrideCleanup):

    def test_a_credential_failure_rolls_the_provider_row_back(self):
        from ai.errors import CredentialUnavailable
        inserted, deleted = [], []
        with patch("api.routes_ai_admin._insert_provider_row",
                   side_effect=lambda row: inserted.append(row["id"])), \
             patch("api.routes_ai_admin._delete_provider_row",
                   side_effect=lambda pid, tid: deleted.append(pid)), \
             patch("api.routes_ai_admin.store_credential",
                   side_effect=CredentialUnavailable("AI_CONFIG_KEY is not set.")), \
             patch("api.routes_ai_admin._get_provider_row", return_value=None):
            resp = _client_as(["admin"]).post(
                "/admin/ai/providers",
                json={"name": "orphan", "provider_type": "OPENAI",
                      "base_url": "https://api.openai.com", "api_key": "sk-test"},
            )
        self.assertEqual(503, resp.status_code, resp.text)
        self.assertEqual(inserted, deleted,
                         "the provider row was not rolled back after the "
                         "credential store failed")

    def test_the_error_explains_what_the_operator_must_do(self):
        from ai.errors import CredentialUnavailable
        with patch("api.routes_ai_admin._insert_provider_row"), \
             patch("api.routes_ai_admin._delete_provider_row"), \
             patch("api.routes_ai_admin.store_credential",
                   side_effect=CredentialUnavailable("AI_CONFIG_KEY is not set.")):
            resp = _client_as(["admin"]).post(
                "/admin/ai/providers",
                json={"name": "orphan", "provider_type": "OPENAI",
                      "base_url": "https://api.openai.com", "api_key": "sk-test"},
            )
        self.assertIn("AI_CONFIG_KEY", resp.text)


# ── M-1 ───────────────────────────────────────────────────────────────────────

class TestM1ProviderFieldValidation(_OverrideCleanup):

    def test_a_base_url_that_is_not_an_http_url_is_refused(self):
        client = _client_as(["admin"])
        for base_url in ("javascript:alert(1)", "file:///etc/passwd",
                         "hello world", "ftp://x/", "http://"):
            with self.subTest(base_url=base_url):
                resp = client.post(
                    "/admin/ai/providers",
                    json={"name": "x", "provider_type": "OPENAI", "base_url": base_url},
                )
                self.assertEqual(422, resp.status_code, resp.text)

    def test_an_over_long_name_is_refused_before_it_reaches_the_database(self):
        resp = _client_as(["admin"]).post(
            "/admin/ai/providers",
            json={"name": "N" * 5000, "provider_type": "OPENAI",
                  "base_url": "https://a.example"},
        )
        self.assertEqual(422, resp.status_code, resp.text)

    def test_an_empty_base_url_is_still_allowed(self):
        """Ollama rows legitimately carry no base_url; the default must hold."""
        from api.routes_ai_admin import ProviderIn
        ProviderIn(name="local", provider_type="OLLAMA", base_url="")


# ── M-2 ───────────────────────────────────────────────────────────────────────

class TestM2EgressClassification(unittest.TestCase):

    def test_link_local_metadata_addresses_are_external(self):
        from api.routes_ai_admin import derive_egress_class
        for url in ("http://169.254.169.254", "http://169.254.170.2/creds"):
            with self.subTest(url=url):
                self.assertEqual("external", derive_egress_class("OPENAI", url))

    def test_loopback_and_rfc1918_remain_local(self):
        from api.routes_ai_admin import derive_egress_class
        for url in ("http://localhost:11434", "http://127.0.0.1:11434",
                    "http://10.1.2.3", "http://192.168.0.9", "http://172.16.5.5"):
            with self.subTest(url=url):
                self.assertEqual("local", derive_egress_class("OLLAMA", url))

    def test_public_hosts_are_external(self):
        from api.routes_ai_admin import derive_egress_class
        self.assertEqual("external", derive_egress_class("OPENAI", "https://api.openai.com"))


# ── M-3 ───────────────────────────────────────────────────────────────────────

class TestM3PolicyReferentialIntegrity(_OverrideCleanup):

    def test_a_default_model_that_does_not_exist_is_refused(self):
        with patch("api.routes_ai_admin._get_model_row", return_value=None), \
             patch("api.routes_ai_admin._upsert_policy_row") as upsert:
            resp = _client_as(["admin"]).put(
                "/admin/ai/policy",
                json={"allow_user_selection": False, "fallback_enabled": True,
                      "default_chat_model_id": "00000000-0000-0000-0000-000000000000"},
            )
        self.assertEqual(400, resp.status_code, resp.text)
        upsert.assert_not_called()

    def test_an_inactive_default_model_is_refused(self):
        row = {"id": "m1", "is_active": False, "purpose": "CHAT"}
        with patch("api.routes_ai_admin._get_model_row", return_value=row), \
             patch("api.routes_ai_admin._upsert_policy_row") as upsert:
            resp = _client_as(["admin"]).put(
                "/admin/ai/policy",
                json={"allow_user_selection": False, "fallback_enabled": True,
                      "default_chat_model_id": "m1"},
            )
        self.assertEqual(400, resp.status_code, resp.text)
        upsert.assert_not_called()

    def test_a_valid_active_model_is_accepted(self):
        row = {"id": "m1", "is_active": True, "purpose": "CHAT"}
        with patch("api.routes_ai_admin._get_model_row", return_value=row), \
             patch("api.routes_ai_admin._upsert_policy_row"), \
             patch("api.routes_ai_admin._invalidate"), \
             patch("api.routes_ai_admin._policy_out", return_value={"ok": True}):
            resp = _client_as(["admin"]).put(
                "/admin/ai/policy",
                json={"allow_user_selection": False, "fallback_enabled": True,
                      "default_chat_model_id": "m1"},
            )
        self.assertEqual(200, resp.status_code, resp.text)

    def test_clearing_the_default_is_allowed(self):
        with patch("api.routes_ai_admin._upsert_policy_row"), \
             patch("api.routes_ai_admin._invalidate"), \
             patch("api.routes_ai_admin._policy_out", return_value={"ok": True}):
            resp = _client_as(["admin"]).put(
                "/admin/ai/policy",
                json={"allow_user_selection": False, "fallback_enabled": True,
                      "default_chat_model_id": None},
            )
        self.assertEqual(200, resp.status_code, resp.text)


# ── M-4 ───────────────────────────────────────────────────────────────────────

class TestM4McpKeyIssuanceIsNotAGet(_OverrideCleanup):

    def test_reading_the_setup_twice_does_not_change_the_key(self):
        client = _client_as(["read_only"], user_id="keyholder")
        keys = {}
        with patch.object(server, "_load_mcp_keys", lambda: keys), \
             patch.object(server, "_save_mcp_keys", lambda k: keys.update(k)):
            first = client.get("/mcp/my-setup")
            self.assertEqual(200, first.status_code, first.text)
            second = client.get("/mcp/my-setup")
        self.assertEqual(200, second.status_code, second.text)
        self.assertIsNone(
            second.json().get("mcp_key"),
            "a second GET minted a new key and revoked the first",
        )

    def test_rotation_is_available_as_an_explicit_post(self):
        client = _client_as(["read_only"], user_id="keyholder")
        keys = {}
        with patch.object(server, "_load_mcp_keys", lambda: keys), \
             patch.object(server, "_save_mcp_keys", lambda k: keys.update(k)):
            first = client.post("/mcp/my-setup").json()["mcp_key"]
            second = client.post("/mcp/my-setup").json()["mcp_key"]
        self.assertTrue(first and second)
        self.assertNotEqual(first, second)


# ── M-5 ───────────────────────────────────────────────────────────────────────

class TestM5DeletingAConversationClearsItsMemory(unittest.TestCase):

    def tearDown(self):
        server._clear_all_sessions()

    def test_the_in_memory_transcript_is_evicted(self):
        server._clear_all_sessions()
        uid, sid = "owner", "sess-abc"
        agent = server._get_agent(f"{uid}:{sid}")
        agent.conversation_history = [{"role": "user", "content": "MY SECRET IS 42"}]

        with patch.object(server, "_HISTORY_ENABLED", True), \
             patch.object(server, "_delete_conversation", return_value=True):
            server.delete_conv(sid, {"user_id": uid, "roles": ["fi_co_analyst"]})

        self.assertNotIn(f"{uid}:{sid}", server._session_agents,
                         "the agent (and its transcript) survived the delete")

    def test_one_users_delete_does_not_evict_anothers_session(self):
        server._clear_all_sessions()
        server._get_agent("alice:shared")
        server._get_agent("bob:shared")
        with patch.object(server, "_HISTORY_ENABLED", True), \
             patch.object(server, "_delete_conversation", return_value=True):
            server.delete_conv("shared", {"user_id": "alice", "roles": []})
        self.assertIn("bob:shared", server._session_agents)


# ── M-6 ───────────────────────────────────────────────────────────────────────

class TestM6AuditDateFiltersAreValidated(_OverrideCleanup):

    def test_an_unparseable_from_ts_is_a_422_not_an_empty_result(self):
        resp = _client_as(["admin"]).get("/audit/logs?from_ts=not-a-date")
        self.assertEqual(422, resp.status_code, resp.text)

    def test_an_unparseable_to_ts_on_stats_is_a_422(self):
        resp = _client_as(["admin"]).get("/audit/stats?to_ts=zzz")
        self.assertEqual(422, resp.status_code, resp.text)

    def test_a_valid_iso_timestamp_is_accepted(self):
        with patch.object(server, "_ACTIVITY_DB", True), \
             patch.object(server, "_query_activity", return_value=[]), \
             patch.object(server, "_count_activity", return_value=0):
            resp = _client_as(["admin"]).get("/audit/logs?from_ts=2026-01-01T00:00:00")
        self.assertEqual(200, resp.status_code, resp.text)


# ── M-8 ───────────────────────────────────────────────────────────────────────

class TestM8McpInventoryIsAdminOnly(_OverrideCleanup):

    def test_a_non_admin_cannot_list_mcp_servers(self):
        resp = _client_as(["read_only"]).get("/config/mcp-servers")
        self.assertEqual(403, resp.status_code, resp.text)

    def test_an_admin_still_can(self):
        resp = _client_as(["admin"]).get("/config/mcp-servers")
        self.assertEqual(200, resp.status_code, resp.text)


# ── L-1 ───────────────────────────────────────────────────────────────────────

class TestL1ContentSecurityPolicy(unittest.TestCase):

    def test_every_response_carries_a_csp(self):
        resp = TestClient(server.app).get("/")
        csp = resp.headers.get("content-security-policy")
        self.assertTrue(csp, "no Content-Security-Policy header")
        self.assertIn("default-src", csp)
        self.assertIn("frame-ancestors 'none'", csp)

    def test_the_existing_hardening_headers_are_untouched(self):
        h = TestClient(server.app).get("/").headers
        self.assertEqual("nosniff", h.get("x-content-type-options"))
        self.assertEqual("DENY", h.get("x-frame-options"))
        self.assertTrue(h.get("referrer-policy"))
        self.assertTrue(h.get("permissions-policy"))


# ── L-2 ───────────────────────────────────────────────────────────────────────

class TestL2DeletingAnAbsentProvider(_OverrideCleanup):

    def test_deleting_a_provider_that_does_not_exist_is_a_404(self):
        with patch("api.routes_ai_admin._get_provider_row", return_value=None):
            resp = _client_as(["admin"]).delete("/admin/ai/providers/not-a-real-id")
        self.assertEqual(404, resp.status_code, resp.text)

    def test_deleting_a_provider_that_exists_still_succeeds(self):
        with patch("api.routes_ai_admin._get_provider_row", return_value={"id": "p1"}), \
             patch("api.routes_ai_admin.delete_credential"), \
             patch("api.routes_ai_admin._delete_provider_row"), \
             patch("api.routes_ai_admin._invalidate"):
            resp = _client_as(["admin"]).delete("/admin/ai/providers/p1")
        self.assertEqual(204, resp.status_code, resp.text)


if __name__ == "__main__":
    unittest.main()
