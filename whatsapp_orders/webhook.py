"""Dependency-free HTTP webhook handler for WhatsApp order webhooks.

Receives a JSON payload from the WhatsApp platform, validates it, and hands it
to :class:`whatsapp_orders.service.WhatsAppOrderSyncService.ingest`.

Expected contract (example):

    {
      "external_provider_id": "whatsapp|917XXXXX2894|20261114-123456",
      "order_source": "whatsapp",
      "customer_name": "Ramesh",
      "customer_phone": "917XXXXX2894",
      "customer_address": "123 Main St, City",
      "items": [{"name":"Paneer Butter Masala","qty":2,"price":240}, ...],
      "total_amount": 480,
      "currency": "INR",
      "restaurant_id": 42,
      "note": "Delivery, no onion",
      "whatsapp_message_sid": "WA MESSAGE SID",
      "whatsapp_phone_number": "917XXXXX2894"
    }

Responses:
    202 Accepted  -> order ingested (PendingApproval).
    400 Bad Request -> malformed payload / missing external_provider_id.
    409 Conflict  -> external_provider_id already has a pending order.
"""

from __future__ import annotations

import json
import logging
from http import HTTPStatus
from typing import Any, Callable, Dict, Optional

from . import service as svc
from .service import WhatsAppOrderSyncService

logger = logging.getLogger(__name__)

# Generic in-memory backend used when no production DB is wired up.
_default_db: Any = None
_service: Optional[WhatsAppOrderSyncService] = None


def get_service() -> WhatsAppOrderSyncService:
    global _service
    if _service is None:
        _service = WhatsAppOrderSyncService(_default_db)
    return _service


def set_backend(db: Any) -> None:
    global _default_db, _service
    _default_db = db
    _service = None


# ---- stdlib-only request handler (works over http.server) ----------------

class WhatsAppOrderHandler:
    """BaseHTTPRequestHandler subclass for the WhatsApp webhook endpoint."""

    def _send(self, status: int, body: Dict[str, Any]) -> None:
        data = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_json(self) -> Optional[Dict[str, Any]]:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return None
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None

    def do_POST(self) -> None:  # noqa: N802
        if self.path.rstrip("/") in ("/webhook", "/webhook/whatsapp", "/api/whatsapp/orders"):
            self._handle_webhook()
        else:
            self._send(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def _handle_webhook(self) -> None:
        payload = self._read_json()
        if payload is None:
            self._send(HTTPStatus.BAD_REQUEST, {"error": "body must be valid JSON"})
            return

        try:
            order = get_service().ingest(payload)
        except svc.MissingExternalProviderIdError:
            self._send(HTTPStatus.BAD_REQUEST, {"error": "missing external_provider_id"})
            return
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("WhatsApp ingest failed: %s", exc)
            self._send(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "ingest failed"})
            return

        self._send(HTTPStatus.ACCEPTED, {
            "received": True,
            "order_status": "PendingApproval",
            "external_provider_id": order.external_provider_id,
            "id": order.id,
        })


if __name__ == "__main__":  # pragma: no cover - manual smoke test
    import argparse
    from http.server import HTTPServer

    parser = argparse.ArgumentParser(description="WhatsApp order webhook receiver")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--db", type=str, default=None, help="sqlite file (default: in-memory)")
    args = parser.parse_args()

    from .sqlite_impl import SQLiteWhatsappOrderDB
    set_backend(SQLiteWhatsappOrderDB(args.db))
    server = HTTPServer(("127.0.0.1", args.port), WhatsAppOrderHandler)
    print(f"Listening on http://127.0.0.1:{args.port} (DB: in-memory/file)")
    server.serve_forever()
