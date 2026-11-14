"""End-to-end tests for the WhatsApp -> main orders sync rules.

Driven against the in-memory SQLite adapter so no external database is needed.
Covers the manual-approval gate and both match/duplicate paths.
"""

import unittest

from whatsapp_orders.sqlite_impl import SQLiteWhatsappOrderDB
from whatsapp_orders.service import (
    MissingExternalProviderIdError,
    NotApprovedError,
    WhatsAppOrderSyncService,
)

MANDATORY_ITEMS = [
    {"name": "Paneer Butter Masala", "qty": 2, "price": 240},
    {"name": "Naan", "qty": 2, "price": 30},
]
TOTAL = 540


def _payload(external_provider_id: str, **overrides) -> dict:
    p = {
        "external_provider_id": external_provider_id,
        "order_source": "whatsapp",
        "restaurant_id": 42,
        "customer_name": "Ramesh Kumar",
        "customer_phone": "917987654321",
        "customer_address": "123 Main St, Chennai",
        "items": MANDATORY_ITEMS,
        "total_amount": TOTAL,
        "currency": "INR",
        "note": "No onion, extra naan",
        "whatsapp_message_sid": "whatsapp_sid_123",
        "whatsapp_phone_number": "917987654321",
    }
    p.update(overrides)
    return p


class TestWhatsAppOrderSync(unittest.TestCase):
    def setUp(self):
        self.db = SQLiteWhatsappOrderDB()
        self.service = WhatsAppOrderSyncService(self.db)

    def test_ingest_creates_pending_order(self):
        order = self.service.ingest(_payload("order-whatsapp-001"))
        self.assertEqual(order.status, "PendingApproval")
        self.assertIsNone(order.synced_to_orders_id)

        # Same order, repeated call should be a no-op (no duplicate row).
        again = self.service.ingest(_payload("order-whatsapp-001"))
        self.assertEqual(again.id, order.id)

    def test_reject_ingest_without_external_provider_id(self):
        with self.assertRaises(MissingExternalProviderIdError):
            self.service.ingest(_payload("order-whatsapp-002") | {"external_provider_id": ""})

    def test_approve_then_duplicated_into_new_main_order(self):
        self.service.ingest(_payload("order-whatsapp-003"))
        approved = self.service.approve("order-whatsapp-003")
        self.assertEqual(approved.status, "Approved")

        main = self.service.match_and_duplicate("order-whatsapp-003")
        self.assertEqual(main.status, "New")

        whatsapp = self.db.get_whatsapp_order("order-whatsapp-003")
        self.assertEqual(whatsapp["status"], "Synced")
        self.assertIsNotNone(whatsapp["synced_to_orders_id"])

        # One main order was created for this WhatsApp order.
        mains = self.db.select_whatsapp_orders_by_status("Synced")
        self.assertEqual(len(mains), 1)

    def test_match_existing_main_order_on_retry(self):
        external_id = "order-whatsapp-004"
        self.service.ingest(_payload(external_id))
        self.service.approve(external_id)
        self.service.match_and_duplicate(external_id)

        # A second sync should be idempotent: reuse the existing main order.
        first_main = self.db.get_main_order_by_external_provider_id(external_id)
        main = self.service.match_and_duplicate(external_id)
        self.assertEqual(main.id, first_main["id"])
        self.assertEqual(main.status, "New")

        whatsapp = self.db.get_whatsapp_order(external_id)
        self.assertEqual(whatsapp["status"], "Synced")
        self.assertEqual(whatsapp["synced_to_orders_id"], first_main["id"])

    def test_refuse_sync_until_manual_approval(self):
        self.service.ingest(_payload("order-whatsapp-005"))
        with self.assertRaises(NotApprovedError):
            self.service.match_and_duplicate("order-whatsapp-005")

    def test_reject_approval_of_already_synced_order(self):
        external_id = "order-whatsapp-006"
        self.service.ingest(_payload(external_id))
        self.service.approve(external_id)
        self.service.match_and_duplicate(external_id)

        with self.assertRaises(NotApprovedError):
            self.service.approve(external_id)


if __name__ == "__main__":
    unittest.main()
