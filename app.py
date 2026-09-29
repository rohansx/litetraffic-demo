"""A tiny multi-tenant records API. Every record belongs to one tenant; a tenant may only read its own."""

from __future__ import annotations

import json
import logging
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("api")

# Test fixtures owned by one LiteTraffic run: {fixture_id: {"run_id": ..., "records": {tenant: {id: record}}}}
FIXTURES: dict[str, dict] = {}
LOCK = Lock()


def can_read(actor: str | None, owner: str, record: dict) -> bool:
    # Records created before sharing existed have no shared_with list.
    return actor == owner or actor in record.get("shared_with", [])


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/health":
            return self._send(200, {"ok": True})
        fixture = self._fixture()
        if fixture is None:
            return self._send(404, {})
        if self.path == "/tenant/state":
            records = fixture["records"]
            return self._send(200, {"tenant_count": len(records), "overlapping_local_ids": all("1" in r for r in records.values())})
        parts = self.path.strip("/").split("/")
        if len(parts) != 4 or parts[0] != "tenants" or parts[2] != "records":
            return self._send(404, {})
        owner, record_id = parts[1], parts[3]
        record = fixture["records"].get(owner, {}).get(record_id)
        if record is None:
            return self._send(404, {})
        if not can_read(self.headers.get("X-Actor-Tenant"), owner, record):
            return self._send(403, {})
        self._send(200, {"tenant": owner, "local_id": record_id, "value": record["value"]})

    def do_POST(self) -> None:
        run_id = self.headers.get("X-LiteTraffic-Run")
        body = self._body()
        parts = self.path.strip("/").split("/")
        if len(parts) == 5 and parts[0] == "tenants" and parts[2] == "records" and parts[4] == "share":
            return self._share(parts[1], parts[3], body.get("tenant"))
        if self.path != "/fixtures" or not run_id or not isinstance(body.get("tenant_a_value"), str) or not isinstance(body.get("tenant_b_value"), str):
            return self._send(404, {})
        fixture_id = uuid.uuid4().hex
        records = {"a": {"1": {"value": body["tenant_a_value"]}}, "b": {"1": {"value": body["tenant_b_value"]}}}
        with LOCK:
            FIXTURES[fixture_id] = {"run_id": run_id, "records": records}
        self._send(201, {"id": fixture_id})

    def do_DELETE(self) -> None:
        fixture_id = self.path.removeprefix("/fixtures/")
        with LOCK:
            if FIXTURES.get(fixture_id, {}).get("run_id") != self.headers.get("X-LiteTraffic-Run"):
                return self._send(404, {})
            del FIXTURES[fixture_id]
        self._send(200, {"deleted": fixture_id})

    def _share(self, owner: str, record_id: str, tenant: object) -> None:
        fixture = self._fixture()
        record = fixture["records"].get(owner, {}).get(record_id) if fixture else None
        if record is None or not isinstance(tenant, str):
            return self._send(404, {})
        if self.headers.get("X-Actor-Tenant") != owner:
            return self._send(403, {})
        with LOCK:
            record.setdefault("shared_with", []).append(tenant)
        self._send(200, {"tenant": owner, "local_id": record_id, "shared_with": record["shared_with"]})

    def _fixture(self) -> dict | None:
        fixture = FIXTURES.get(self.headers.get("X-LiteTraffic-Fixture", ""))
        return fixture if fixture and fixture["run_id"] == self.headers.get("X-LiteTraffic-Run") else None

    def _body(self) -> dict:
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
        except (TypeError, ValueError):
            return {}
        return body if isinstance(body, dict) else {}

    def _send(self, status: int, body: dict) -> None:
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: object) -> None:
        log.info("%s %s", self.address_string(), format % args)


if __name__ == "__main__":
    log.info("listening on :8080")
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
