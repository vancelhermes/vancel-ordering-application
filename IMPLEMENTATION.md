# WhatsApp Order Integration — Implementation Record

Owner: Gowtham B (Vancel). Collaborator for frontend coordination: John Rohith.
Source task: Vancel Workspace task `361682aa-c03d-46d2-93ac-ac5352cd89ce`.

## What this does
Orders placed through a WhatsApp bot are now routed into the canonical `orders`
table, following the 2026-11-05 "Restaurant Ordering System" design:

1. A WhatsApp bot order arrives as a JSON webhook and is stored in the new
   `whatsapp_phone_orders` table (nullable columns; `external_provider_id` is
   the unique key linking back to `orders`).
2. It sits in `PendingApproval` until a restaurant manager approve it.
3. `match_and_duplicate()` (backend) then moves it into the canonical `orders`
   table — matching the existing row by `external_provider_id`, or duplicating
   it if absent. The WhatsApp row is marked `Synced` and linked via
   `synced_to_orders_id`.

## Files
- `whatsapp_orders/schema.py` — `whatsapp_phone_orders` + reference `orders` DDL
  (PostgreSQL first; SQLite variant for tests).
- `whatsapp_orders/service.py` — match/duplicate + approval gate (idempotent).
- `whatsapp_orders/sqlite_impl.py` — SQLite adapter (tests, no external DB).
- `whatsapp_orders/webhook.py` — dependency-free webhook receiver.
- `migrations/001_whatsapp_phone_orders.sql` — PostgreSQL migration.
- `tests/test_service.py` — 6 passing end-to-end tests.

## Frontend coordination with John Rohith (pending)
Minimal frontend updates are needed so the restaurant POS can (a) approve a
WhatsApp order from the queue, which flips it `PendingApproval -> Approved` in
the `whatsapp_phone_orders` table, and (b) view synced orders. See the email
draft to John Rohith.

## CI/CD follow-up (deferred)
`.github/workflows/ci.yml` is committed in the earlier commit
`98a43cd` but is not yet on `main` because this GitHub token lacks the
`workflow` scope. Re-add it once a token with `workflow` scope is available.
