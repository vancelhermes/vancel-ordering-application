"""Business logic for the WhatsApp -> main orders integration.

The service is intentionally DB-agnostic. A ``db`` adapter that implements the
small ``WhatsAppOrderDB`` protocol is injected, so the same match-and-duplicate
rules run unchanged against PostgreSQL in production and against an in-memory
SQLite database in tests.

Flow:
    1. ingest(payload)  -> inserts a row into whatsapp_phone_orders with
                          status = PendingApproval (manual-approval gate).
    2. approve(id)      -> the restaurant-manager gate. Only Approved orders
                          may move into the canonical orders table.
    3. match_and_duplicate(id) -> find the main order (by external_provider_id);
                                  if one exists, update it; otherwise create a
                                  new main-order row. Record the linkage and mark
                                  the whatsapp row Synced.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from . import (
    ORDER_STATUS_APPROVED,
    ORDER_STATUS_NEW,
    ORDER_STATUS_REJECTED,
    ORDER_STATUS_SYNCED,
)
from .schema import MAIN_ORDERS_CREATE_SQL, WHATSAPP_PHONE_ORDERS_CREATE_SQL

logger = logging.getLogger(__name__)


class OrderSyncError(Exception):
    """Base error for the WhatsApp order sync pipeline."""


class OrderNotFound(OrderSyncError):
    pass


class NotApprovedError(OrderSyncError):
    """The WhatsApp order has not been manually approved yet."""


class MissingExternalProviderIdError(OrderSyncError):
    pass


@dataclass(frozen=True)
class WhatsappOrder:
    id: int
    external_provider_id: str
    order_source: str
    restaurant_id: Optional[int]
    customer_name: Optional[str]
    customer_phone: Optional[str]
    customer_address: Optional[str]
    items: dict[str, Any]
    total_amount: Optional[float]
    currency: str
    note: Optional[str]
    whatsapp_message_sid: Optional[str]
    whatsapp_phone_number: Optional[str]
    status: str
    synced_to_orders_id: Optional[int]
    created_at: Any
    updated_at: Any


@dataclass(frozen=True)
class MainOrder:
    id: int
    external_provider_id: Optional[str]
    restaurant_id: int
    customer_name: Optional[str]
    customer_phone: Optional[str]
    customer_address: Optional[str]
    items: dict[str, Any]
    total_amount: Optional[float]
    currency: str
    status: str
    created_at: Any
    updated_at: Any


@dataclass
class WhatsAppOrderDB:
    """Small protocol that lets the service run against any SQL DB."""

    def insert_whatsapp_order(self, payload: dict[str, Any]) -> int:
        raise NotImplementedError

    def get_whatsapp_order(self, external_provider_id: str) -> Optional[dict[str, Any]]:
        raise NotImplementedError

    def update_whatsapp_order(self, external_provider_id: str, upd: dict[str, Any]) -> None:
        raise NotImplementedError

    def get_main_order_by_external_provider_id(
        self, external_provider_id: str
    ) -> Optional[dict[str, Any]]:
        raise NotImplementedError

    def upsert_main_order(self, payload: dict[str, Any]) -> int:
        """Insert or update a canonical main order; returns the main order id."""
        raise NotImplementedError

    def select_whatsapp_orders_by_status(self, status: str) -> list[dict[str, Any]]:
        raise NotImplementedError


# Canonical mapping from the app's order-status vocabulary onto the sync state.
def _status_normalized(status: Optional[str]) -> str:
    if not status:
        return ORDER_STATUS_NEW
    return status


def _as_dict(row: Any) -> dict[str, Any]:
    if isinstance(row, dict):
        return row
    # Some adapters return row-like objects with attribute access.
    return {k: v for k, v in vars(row).items() if not k.startswith("_")}


class WhatsAppOrderSyncService:
    """Matches / duplicates WhatsApp orders into the main orders table."""

    def __init__(self, db: WhatsAppOrderDB) -> None:
        self.db = db

    # -- ingestion ---------------------------------------------------------

    def ingest(self, payload: dict[str, Any]) -> WhatsappOrder:
        """Create a pending-approval record for a bot-generated order."""
        external_provider_id = payload.get("external_provider_id")
        if not external_provider_id:
            raise MissingExternalProviderIdError(
                "WhatsApp orders require an external_provider_id (unique bot link)"
            )

        existing = self.db.get_whatsapp_order(external_provider_id)
        if existing:
            logger.info(
                "WhatsApp order %r already present (id=%s, status=%s); no dup",
                external_provider_id,
                existing.get("id"),
                existing.get("status"),
            )
            return self._to_dataclass(existing)

        inserted_id = self.db.insert_whatsapp_order(
            {
                "external_provider_id": external_provider_id,
                "order_source": payload.get("order_source", "whatsapp"),
                "restaurant_id": payload.get("restaurant_id"),
                "customer_name": payload.get("customer_name"),
                "customer_phone": payload.get("customer_phone"),
                "customer_address": payload.get("customer_address"),
                "items": payload.get("items", {}),
                "total_amount": payload.get("total_amount"),
                "currency": payload.get("currency", "USD"),
                "note": payload.get("note"),
                "whatsapp_message_sid": payload.get("whatsapp_message_sid"),
                "whatsapp_phone_number": payload.get("whatsapp_phone_number"),
                "status": ORDER_STATUS_NEW,
            }
        )
        record = self.db.get_whatsapp_order(external_provider_id)
        if record is None:
            raise OrderNotFound(f"just-inserted WhatsApp order {external_provider_id} missing")
        return self._to_dataclass(record)

    # -- approval gate -----------------------------------------------------

    def approve(self, external_provider_id: str) -> WhatsappOrder:
        """Manual approval gate: marks the order Approved, then syncs it."""
        order = self.get(external_provider_id)
        if order.status == ORDER_STATUS_APPROVED:
            logger.info("WhatsApp order %r already Approved", external_provider_id)
            return order
        if order.status != ORDER_STATUS_NEW:
            raise NotApprovedError(
                f"Cannot approve order {external_provider_id} (status={order.status})"
            )
        self.db.update_whatsapp_order(external_provider_id, {"status": ORDER_STATUS_APPROVED})
        return self.get(external_provider_id)

    # -- sync --------------------------------------------------------------

    def match_and_duplicate(self, external_provider_id: str) -> MainOrder:
        """Match to an existing main order, else duplicate a new one.

        This is the backend part of the task "integrate WhatsApp orders into
        the main orders table". Manual approval must already have happened.
        """
        order = self.get(external_provider_id)
        if order.status == ORDER_STATUS_SYNCED:
            # Already synced: re-running must be idempotent and return the main
            # order that was previously created for this WhatsApp order.
            main = self.db.get_main_order_by_external_provider_id(external_provider_id)
            if main is None:
                raise OrderNotFound(external_provider_id)
            return self.get_main_order(main["id"])
        if order.status != ORDER_STATUS_APPROVED:
            raise NotApprovedError(
                f"Order {external_provider_id} is {order.status}; manual approval required"
            )

        main = self.db.get_main_order_by_external_provider_id(external_provider_id)

        payload: dict[str, Any] = {
            "external_provider_id": external_provider_id,
            "restaurant_id": order.restaurant_id,
            "customer_name": order.customer_name,
            "customer_phone": order.customer_phone,
            "customer_address": order.customer_address,
            "items": order.items,
            "total_amount": order.total_amount,
            "currency": order.currency,
            # Main orders use the app's "New" status; the WhatsApp table uses
            # "PendingApproval" for its own gate, so they stay distinct.
            "status": "New",
        }

        if main is None:
            main_id = self.db.upsert_main_order(payload)
            logger.info(
                "Duplicated WhatsApp order %r into new main order id=%s",
                external_provider_id,
                main_id,
            )
        else:
            # Order already exists on the main side (e.g. backfill/retry).
            main_id = main["id"]
            logger.info(
                "Matched WhatsApp order %r to existing main order id=%s",
                external_provider_id,
                main_id,
            )
            # Keep the canonical order's status in sync with the pipeline.
            self.db.update_main_order(main_id, {"status": "New"})

        self.db.update_whatsapp_order(external_provider_id, {
            "status": ORDER_STATUS_SYNCED,
            "synced_to_orders_id": main_id,
        })
        return self.get_main_order(main_id)

    # -- lookup helpers ----------------------------------------------------

    def get(self, external_provider_id: str) -> WhatsappOrder:
        record = self.db.get_whatsapp_order(external_provider_id)
        if record is None:
            raise OrderNotFound(external_provider_id)
        return self._to_dataclass(record)

    def get_main_order(self, main_id: int) -> MainOrder:
        main = self.db.get_main_order_by_id(main_id)
        if main is None:
            raise OrderNotFound(f"main order {main_id}")
        return self._to_main_dataclass(main)

    @staticmethod
    def _to_dataclass(record: dict[str, Any]) -> WhatsappOrder:
        d = _as_dict(record)
        return WhatsappOrder(
            id=d.get("id"),
            external_provider_id=d["external_provider_id"],
            order_source=d.get("order_source"),
            restaurant_id=d.get("restaurant_id"),
            customer_name=d.get("customer_name"),
            customer_phone=d.get("customer_phone"),
            customer_address=d.get("customer_address"),
            items=d.get("items", {}),
            total_amount=d.get("total_amount"),
            currency=d.get("currency", "USD"),
            note=d.get("note"),
            whatsapp_message_sid=d.get("whatsapp_message_sid"),
            whatsapp_phone_number=d.get("whatsapp_phone_number"),
            status=d["status"],
            synced_to_orders_id=d.get("synced_to_orders_id"),
            created_at=d.get("created_at"),
            updated_at=d.get("updated_at"),
        )

    @staticmethod
    def _to_main_dataclass(record: dict[str, Any]) -> MainOrder:
        d = _as_dict(record)
        return MainOrder(
            id=d["id"],
            external_provider_id=d.get("external_provider_id"),
            restaurant_id=d["restaurant_id"],
            customer_name=d.get("customer_name"),
            customer_phone=d.get("customer_phone"),
            customer_address=d.get("customer_address"),
            items=d.get("items", {}),
            total_amount=d.get("total_amount"),
            currency=d.get("currency", "USD"),
            status=d["status"],
            created_at=d.get("created_at"),
            updated_at=d.get("updated_at"),
        )


__all__ = [
    "OrderSyncError",
    "OrderNotFound",
    "NotApprovedError",
    "MissingExternalProviderIdError",
    "WhatsappOrder",
    "MainOrder",
    "WhatsappOrderDB",
    "WhatsAppOrderSyncService",
    "WHATSAPP_PHONE_ORDERS_CREATE_SQL",
    "MAIN_ORDERS_CREATE_SQL",
]
