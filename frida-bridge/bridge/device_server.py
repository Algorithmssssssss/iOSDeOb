"""Tiny local HTTP JSON API so the web UI (running in the browser on this
same Mac) can list/add/remove Frida devices instantly — listing devices or
registering a remote one takes milliseconds, so this doesn't go through the
Celery/API path built for long-running trace runs. Runs in a background
thread inside the same process as the Celery worker (started from
celery_app.py) so it shares one frida.DeviceManager with the actual trace
runner — a remote device added here is the same one runner.py sees.

No auth: binds to 127.0.0.1 only, and the worst a caller can do is list or
register/deregister Frida devices — nothing that touches app data or starts
a trace by itself.
"""

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import device_manager

PORT = int(os.environ.get("DEVICE_SERVER_PORT", "5577"))


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):  # noqa: A002 - matches base signature
        pass  # keep the Celery worker's console output uncluttered

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length))

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        if self.path == "/devices":
            try:
                self._send_json(200, {"devices": device_manager.list_devices()})
            except Exception as exc:
                self._send_json(500, {"error": str(exc)})
            return
        self._send_json(404, {"error": "not found"})

    def do_POST(self):
        if self.path == "/devices/remote":
            try:
                body = self._read_json_body()
                address = (body.get("address") or "").strip()
                if not address:
                    self._send_json(400, {"error": "address is required"})
                    return
                device = device_manager.add_remote_device(address)
                self._send_json(200, {"device": device})
            except Exception as exc:
                self._send_json(400, {"error": str(exc)})
            return
        self._send_json(404, {"error": "not found"})

    def do_DELETE(self):
        if self.path == "/devices/remote":
            try:
                body = self._read_json_body()
                address = (body.get("address") or "").strip()
                if not address:
                    self._send_json(400, {"error": "address is required"})
                    return
                device_manager.remove_remote_device(address)
                self._send_json(200, {"ok": True})
            except Exception as exc:
                self._send_json(400, {"error": str(exc)})
            return
        self._send_json(404, {"error": "not found"})


def start_in_background() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    thread = threading.Thread(target=server.serve_forever, name="device-server", daemon=True)
    thread.start()
