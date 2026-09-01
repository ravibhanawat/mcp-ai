"""The fake provider server is test infrastructure every adapter test depends on,
so it gets its own tests — a silently broken fake produces false green suites."""
import json
import unittest
import urllib.error
import urllib.request

from tests.fakes.fake_provider_server import FakeProviderServer


def post(url, body):
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        return resp.status, json.loads(resp.read())


class TestFakeProviderServer(unittest.TestCase):

    def test_ok_mode_returns_openai_shaped_response(self):
        with FakeProviderServer(mode="ok") as server:
            status, body = post(f"{server.base_url}/v1/chat/completions", {"model": "m"})
            self.assertEqual(200, status)
            self.assertIn("choices", body)

    def test_records_received_requests(self):
        with FakeProviderServer(mode="ok") as server:
            post(f"{server.base_url}/v1/chat/completions", {"model": "recorded-model"})
            self.assertEqual(1, len(server.requests))
            self.assertEqual("recorded-model", server.requests[0]["model"])

    def test_unauthorized_mode_returns_401(self):
        with FakeProviderServer(mode="unauthorized") as server:
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                post(f"{server.base_url}/v1/chat/completions", {})
            self.assertEqual(401, ctx.exception.code)

    def test_rate_limited_mode_returns_429(self):
        with FakeProviderServer(mode="rate_limited") as server:
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                post(f"{server.base_url}/v1/chat/completions", {})
            self.assertEqual(429, ctx.exception.code)

    def test_malformed_mode_returns_non_json(self):
        with FakeProviderServer(mode="malformed") as server:
            req = urllib.request.Request(
                f"{server.base_url}/v1/chat/completions", data=b"{}",
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                self.assertNotIn(b"choices", resp.read())

    def test_mode_can_be_changed_mid_test(self):
        """Fallback tests need a provider that fails, then a different one that works."""
        with FakeProviderServer(mode="ok") as server:
            post(f"{server.base_url}/v1/chat/completions", {})
            server.mode = "unauthorized"
            with self.assertRaises(urllib.error.HTTPError):
                post(f"{server.base_url}/v1/chat/completions", {})

    def test_unavailable_mode_refuses_connections(self):
        with FakeProviderServer(mode="ok") as server:
            url = server.base_url
            server.mode = "unavailable"
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                post(f"{url}/v1/chat/completions", {})
            self.assertEqual(503, ctx.exception.code)


if __name__ == "__main__":
    unittest.main()
