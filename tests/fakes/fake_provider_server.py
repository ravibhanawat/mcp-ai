"""
An in-process HTTP server that impersonates an LLM provider.

Every adapter and fallback test in the suite needs a backend that can be told to
fail in a specific way. Mocking `requests` would test the mock; this tests the
adapter's real socket handling, timeout behaviour and error mapping.

Serves the union of the Ollama, OpenAI and Anthropic surfaces so one fake covers
all four adapters:
    POST /api/chat                  Ollama chat
    POST /api/embeddings            Ollama embeddings
    GET  /api/tags                  Ollama model list
    POST /v1/chat/completions       OpenAI-compatible chat
    POST /v1/embeddings             OpenAI-compatible embeddings
    GET  /v1/models                 OpenAI-compatible model list
    POST /v1/messages               Anthropic messages
"""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

#: How long "slow" mode sleeps. Longer than any adapter timeout used in tests.
SLOW_DELAY_SECONDS = 5.0

MODES = ("ok", "unavailable", "slow", "unauthorized", "rate_limited", "malformed")


class _Handler(BaseHTTPRequestHandler):

    # Silence per-request logging so pytest output stays readable.
    def log_message(self, fmt, *args):
        pass

    @property
    def _server(self):
        return self.server.fake

    def _send(self, status: int, payload, raw: bool = False):
        body = payload if raw else json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/plain" if raw else "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _guard(self) -> bool:
        """Apply the current failure mode. Returns True if the request was handled."""
        mode = self._server.mode
        if mode == "unavailable":
            self._send(503, {"error": "service unavailable"})
            return True
        if mode == "unauthorized":
            self._send(401, {"error": {"message": "invalid api key"}})
            return True
        if mode == "rate_limited":
            self._send(429, {"error": {"message": "rate limit exceeded"}})
            return True
        if mode == "slow":
            time.sleep(SLOW_DELAY_SECONDS)
        if mode == "malformed":
            self._send(200, b"not json at all", raw=True)
            return True
        return False

    def do_GET(self):
        if self._guard():
            return
        if self.path.startswith("/api/tags"):
            self._send(200, {"models": [{"name": self._server.model_name}]})
        elif self.path.startswith("/v1/models"):
            self._send(200, {"data": [{"id": self._server.model_name}]})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw)
        except ValueError:
            body = {}
        self._server.requests.append(body)
        self._server.headers_seen.append(dict(self.headers))

        if self._guard():
            return

        reply = self._server.reply_text
        if self.path.startswith("/api/chat"):
            if body.get("stream"):
                self._send_ollama_stream(reply)
            else:
                self._send(200, {"message": {"role": "assistant", "content": reply},
                                 "prompt_eval_count": 11, "eval_count": 7})
        elif self.path.startswith("/api/embeddings"):
            self._send(200, {"embedding": [0.1, 0.2, 0.3]})
        elif self.path.startswith("/v1/chat/completions"):
            if body.get("stream"):
                self._send_sse_stream(reply)
            else:
                self._send(200, {
                    "choices": [{"message": {"role": "assistant", "content": reply}}],
                    "usage": {"prompt_tokens": 11, "completion_tokens": 7},
                })
        elif self.path.startswith("/v1/embeddings"):
            self._send(200, {"data": [{"embedding": [0.1, 0.2, 0.3]}]})
        elif self.path.startswith("/v1/messages"):
            self._send(200, {
                "content": [{"type": "text", "text": reply}],
                "usage": {"input_tokens": 11, "output_tokens": 7},
            })
        else:
            self._send(404, {"error": "not found"})

    def _send_ollama_stream(self, reply: str):
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.end_headers()
        for token in reply.split(" "):
            self.wfile.write(
                json.dumps({"message": {"content": token + " "}, "done": False}).encode() + b"\n"
            )
            self.wfile.flush()
        self.wfile.write(json.dumps({"message": {"content": ""}, "done": True}).encode() + b"\n")
        self.wfile.flush()

    def _send_sse_stream(self, reply: str):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        for token in reply.split(" "):
            chunk = {"choices": [{"delta": {"content": token + " "}}]}
            self.wfile.write(b"data: " + json.dumps(chunk).encode() + b"\n\n")
            self.wfile.flush()
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()


class FakeProviderServer:
    """Context manager yielding a running fake provider.

    Usage:
        with FakeProviderServer(mode="ok") as server:
            adapter = OllamaProvider(config_pointing_at(server.base_url))
            ...
            server.mode = "unavailable"   # change behaviour mid-test
    """

    def __init__(self, mode: str = "ok", reply_text: str = "hello from the fake",
                 model_name: str = "configured-test-model"):
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}")
        self.mode = mode
        self.reply_text = reply_text
        self.model_name = model_name
        self.requests: list[dict] = []
        self.headers_seen: list[dict] = []
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def base_url(self) -> str:
        assert self._httpd is not None, "server not started"
        port = self._httpd.server_address[1]
        return f"http://127.0.0.1:{port}"

    def __enter__(self) -> "FakeProviderServer":
        # Threaded so a slow-mode handler blocked in time.sleep() doesn't make
        # shutdown() in __exit__ wait for it to finish (daemon_threads=True by
        # default on ThreadingHTTPServer, so no thread outlives the process either).
        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self._httpd.fake = self          # handler reads state from here
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc):
        if self._httpd:
            self._httpd.shutdown()
            self._httpd.server_close()
        if self._thread:
            self._thread.join(timeout=5)
        return False
