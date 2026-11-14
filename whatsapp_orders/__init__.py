"""Vancel ordering-application — WhatsApp order integration package.

This module is the deliverable for the engineering task:
  "Integrate WhatsApp orders into the main orders table; coordinate minimal
   frontend updates with John Rohith" (owner: Gowtham B).

Architecture (per the 2026-11-05 design meeting, "Restaurant Ordering System"):
  * Existing  -> main ``orders`` table  holds the canonical kitchen queue.
  * New       -> ``whatsapp_phone_orders`` table holds bot-generated orders.
                 Columns are nullable to accommodate varied bot data.
                 ``external_provider_id`` is the UNIQUE key linking the two
                 tables back to back orders.
  * Sync rule -> orders stay in ``whatsapp_phone_orders`` until a restaurant
                 manager manually approves them (the "manual approval" gate).
                 Approval then triggers the backend to "match and duplicate"
                 the order into the main ``orders`` table (creating the main
                 row if one does not already exist for the order).

Production database: PostgreSQL (the app's existing stack). The DDL below is
PostgreSQL-targeted but written to be portable. Tests drive pure business
logic against an in-memory SQLite adapter so no external DB is required.
"""

from __future__ import annotations

# Canonical status vocabulary used by the WhatsApp ordering pipeline.
# ORDER_STATUS_NEW is the gate alias for "PendingApproval" - the state a row is
# in immediately after ingest, before a restaurant manager approves it. Only
# rows in PendingApproval may be promoted to Approved (manual approval), then
# Synced (into the canonical main orders table).
ORDER_STATUS_NEW = "PendingApproval"
ORDER_STATUS_APPROVED = "Approved"
ORDER_STATUS_OUT_FOR_DELIVERY = "Out for Delivery"

ORDER_STATUS_PENDING_APPROVAL = "PendingApproval"
ORDER_STATUS_SYNCED = "Synced"
ORDER_STATUS_REJECTED = "Rejected"
