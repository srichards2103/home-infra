"""An intentionally small, loopback-only application for deployment acceptance tests."""

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from socketserver import TCPServer


class LoopbackServer(ThreadingHTTPServer):
    def server_bind(self):
        # HTTPServer normally performs a reverse DNS lookup during construction.
        # A loopback health endpoint must start even when DNS is unavailable.
        TCPServer.server_bind(self)
        self.server_name = "localhost"
        self.server_port = self.server_address[1]


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path not in ("/", "/healthz"):
            self.send_error(404)
            return
        payload = json.dumps(
            {
                "status": "ok",
                "service": "hello",
                "release": os.environ.get("HOMEINFRA_RELEASE", "development"),
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format, *args):
        pass  # Avoid logging health probes and arbitrary client-controlled strings.


if __name__ == "__main__":
    LoopbackServer(("127.0.0.1", int(os.environ.get("PORT", "8090"))), Handler).serve_forever()
