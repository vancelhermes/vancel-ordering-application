# vancel-ordering-application

Restaurant ordering application — WhatsApp order integration (owner: Gowtham B).
Deliverables for task `361682aa-c03d-46d2-93ac-ac5352cd89ce` in Vancel Workspace:
integrate orders placed through a WhatsApp bot into the canonical main `orders`
table, with manual approval and minimal frontend coordination with John Rohith.

## Architecture

```
WhatsApp Business API
        |
        |  JSON webhook (see webhook.py / REST 202)
        v
whatsapp_phone_orders   (source of truth for bot orders)
  - nullable columns (accommodate varied bot payloads)
  - external_provider_id  => UNIQUE key linking back to main orders
  - status: PendingApproval | Approved | Synced | Rejected
        |
        |  manual approval by restaurant manager (approve())
        v
canonical orders        (kitchen queue; New -> Preparing -> ...)
  - status: New | Preparing | Out for Delivery | ...
        |
        |  match_and_duplicate()
        v
main orders row linked via external_provider_id + synced_to_orders_id
```

## Rules

1. **Ingest** always lands in `whatsapp_phone_orders` with status `PendingApproval`.
2. **Manual approval** is a restaurant-manager gate (the `approve()` method).
   Unapproved orders never reach the main orders table.
3. **Match & duplicate** is the backend: find the main order by
   `external_provider_id`; if it exists, reuse it ("match"); otherwise create a
   new main-order row ("duplicate"). Then mark the WhatsApp row `Synced` and
   link it via `synced_to_orders_id`.
4. Re-running the sync is **idempotent** (already-synced orders return the same
   main order).

## Stack & environment

Production: PostgreSQL (app's existing stack).
Local/dev: in-memory SQLite adapter (no external server required; used by tests).

## How to run

```bash
# run the unit tests
python3 -m unittest discover -s tests -v

# optionally serve the webhook endpoint locally (uses an in-memory DB by default)
python3 -m whatsapp_orders.webhook --port 8000
```

## Where the pieces live

| Path | Purpose |
|------|---------|
| `whatsapp_orders/schema.py` | DDL for `orders` (reference) and `whatsapp_phone_orders` (PG + SQLite) |
| `whatsapp_orders/service.py` | Match/duplicate business logic, approval gate |
| `whatsapp_orders/sqlite_impl.py` | SQLite adapter (tests + local dev) |
| `whatsapp_orders/webhook.py` | Dependency-free HTTP webhook receiver |
| `tests/test_service.py` | End-to-end sync tests |
| `migrations/001_whatsapp_phone_orders.sql` | PostgreSQL migration |
