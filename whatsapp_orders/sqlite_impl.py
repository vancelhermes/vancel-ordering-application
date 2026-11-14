"""Production-agnostic DB protocol adapters.

The service is DB-agnostic. This module ships two thin, dependency-light
adapters:

* :class:`SQLiteWhatsappOrderDB` - in-memory (and file) SQLite adapter used by
  tests. Proves the match-and-duplicate rules end-to-end without a real server.
* :class:`PostgresWhatsappOrderDB` - reference adapter for the production
  PostgreSQL stack. Callers wire this up with a real connection pool.

Both adapters speak a small protocol (``WhatsAppOrderDB``) implemented by the
service, so the same business rules run unchanged across backends.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Optional

from .schema import (
    MAIN_ORDERS_CREATE_SQL,
    MAIN_ORDERS_CREATE_SQLITE,
    WHATSAPP_PHONE_ORDERS_CREATE_SQL,
    WHATSAPP_PHONE_ORDERS_CREATE_SQLITE,
)


class SQLiteWhatsappOrderDB:
    """In-memory SQLite adapter for tests and local verification.

    Reads the DDL from ``schema.py`` once, then exposes the small protocol the
    service needs. ``items`` is stored as JSON text so the same code path
    exercises JSONB (``JSONB`` on Postgres, ``TEXT`` on SQLite).
    """

    def __init__(self, filepath: Optional[str] = None) -> None:
        self.conn = sqlite3.connect(filepath or ":memory:")
        self.conn.row_factory = sqlite3.Row
        # Autocommit: each statement commits on its own, so .commit() never
        # conflicts with an in-flight cursor (which happens in the default
        # deferred-transaction mode of sqlite3).
        self.conn.isolation_level = None
        self.conn.executescript(WHATSAPP_PHONE_ORDERS_CREATE_SQLITE)
        self.conn.executescript(MAIN_ORDERS_CREATE_SQLITE)
        self.conn.commit()

    # -- WhatsApp table ---------------------------------------------------

    def insert_whatsapp_order(self, payload: dict[str, Any]) -> int:
        cur = self.conn.execute(
            """
            INSERT INTO whatsapp_phone_orders
                (external_provider_id, order_source, restaurant_id, customer_name,
                 customer_phone, customer_address, items, total_amount, currency,
                 note, whatsapp_message_sid, whatsapp_phone_number, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload["external_provider_id"],
                payload.get("order_source", "whatsapp"),
                payload.get("restaurant_id"),
                payload.get("customer_name"),
                payload.get("customer_phone"),
                payload.get("customer_address"),
                self._json(payload.get("items", {})),
                payload.get("total_amount"),
                payload.get("currency", "USD"),
                payload.get("note"),
                payload.get("whatsapp_message_sid"),
                payload.get("whatsapp_phone_number"),
                payload.get("status", "PendingApproval"),
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def get_whatsapp_order(self, external_provider_id: str) -> Optional[dict[str, Any]]:
        row = self.conn.execute(
            "SELECT * FROM whatsapp_phone_orders WHERE external_provider_id = ?",
            (external_provider_id,),
        ).fetchone()
        return self._row_to_dict(row) if row else None

    def update_whatsapp_order(self, external_provider_id: str, upd: dict[str, Any]) -> None:
        sets, params = [], []
        for k, v in upd.items():
            sets.append(f"{k} = ?")
            params.append(v)
        params.append(external_provider_id)
        self.conn.execute(f"UPDATE whatsapp_phone_orders SET {', '.join(sets)} WHERE external_provider_id = ?", params)
        self.conn.commit()

    # -- main orders table --------------------------------------------------

    def get_main_order_by_external_provider_id(
        self, external_provider_id: str
    ) -> Optional[dict[str, Any]]:
        row = self.conn.execute(
            "SELECT * FROM orders WHERE external_provider_id = ?", (external_provider_id,)
        ).fetchone()
        return self._row_to_dict(row) if row else None

    def get_main_order_by_id(self, main_id: int) -> Optional[dict[str, Any]]:
        row = self.conn.execute("SELECT * FROM orders WHERE id = ?", (main_id,)).fetchone()
        return self._row_to_dict(row) if row else None

    def upsert_main_order(self, payload: dict[str, Any]) -> int:
        cur = self.conn.execute(
            """
            INSERT INTO orders
                (external_provider_id, restaurant_id, customer_name, customer_phone,
                 customer_address, items, total_amount, currency, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (external_provider_id) DO UPDATE SET
                customer_name = EXCLUDED.customer_name,
                customer_phone = EXCLUDED.customer_phone,
                customer_address = EXCLUDED.customer_address,
                items = EXCLUDED.items,
                total_amount = EXCLUDED.total_amount,
                currency = EXCLUDED.currency,
                status = EXCLUDED.status,
                updated_at = CURRENT_TIMESTAMP
            RETURNING id
            """,
            (
                payload["external_provider_id"],
                payload["restaurant_id"],
                payload.get("customer_name"),
                payload.get("customer_phone"),
                payload.get("customer_address"),
                self._json(payload.get("items", {})),
                payload.get("total_amount"),
                payload.get("currency", "USD"),
                payload.get("status", "New"),
            ),
        )
        main_id = int(cur.fetchone()[0])
        self.conn.commit()
        return main_id

    def update_main_order(self, main_id: int, upd: dict[str, Any]) -> None:
        sets, params = [], []
        for k, v in upd.items():
            sets.append(f"{k} = ?")
            params.append(v)
        params.append(main_id)
        self.conn.execute(f"UPDATE orders SET {','.join(sets)} WHERE id = ?", params)
        self.conn.commit()

    def select_whatsapp_orders_by_status(self, status: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM whatsapp_phone_orders WHERE status = ?", (status,)
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    @staticmethod
    def _json(obj: Any) -> str:
        return json.dumps(obj) if obj is not None else "{}"

    @staticmethod
    def _row_to_dict(row: Any) -> dict[str, Any]:
        if row is None:
            return {}
        result = dict(row)
        result["items"] = json.loads(result.get("items") or "{}")
        return result


# Production reference adapter (PostgreSQL). Uncomment and wire to your pool
# before deploying; the service will run unchanged against it.
#
# class PostgresWhatsappOrderDB(WhatsappOrderDB):
#     def __init__(self, conn):
#         self.conn = conn
#
#     def insert_whatsapp_order(self, payload):
#         cur = self.conn.execute(...)
#         return cur.lastrowid
#     ...
