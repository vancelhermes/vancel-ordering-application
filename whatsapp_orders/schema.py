"""DDL for the new ``whatsapp_phone_orders`` table and a reference main
``orders`` table, as captured in the 2026-11-05 design meeting.

Both files are PostgreSQL first. The WhatsApp table uses nullable columns so
the bot can send a varied payload, and ``external_provider_id`` as the UNIQUE
key that links back to ``orders``.

The ``orders`` DDL here is a *reference* representation of the app's canonical
main orders table (based on the New -> Preparing -> Out for Delivery status
sync documented in the meeting). Replace the body with the exact DDL from the
existing orders migration before deploying.
"""

from __future__ import annotations

# --------------------------------------------------------------------------
# Canonical status vocabulary for the WhatsApp ordering pipeline.
# "PendingApproval" is the gate immediately after ingest; only rows in that
# state may be promoted to Approved (manual approval), then Synced (into the
# canonical main orders table). Values match the CHECK constraint in the DDL.
# --------------------------------------------------------------------------
ORDER_STATUS_PENDING_APPROVAL = "PendingApproval"
ORDER_STATUS_APPROVED = "Approved"
ORDER_STATUS_SYNCED = "Synced"
ORDER_STATUS_REJECTED = "Rejected"

# Alias mirroring the app's existing order-status vocabulary.
ORDER_STATUS_NEW = "PendingApproval"
MAIN_ORDERS_CREATE_SQL = r"""
CREATE TABLE IF NOT EXISTS orders (
    id                 BIGINT           GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    external_provider_id VARCHAR(255)   UNIQUE,          -- bot/provider link key
    restaurant_id      BIGINT           NOT NULL,
    customer_name      VARCHAR(255),
    customer_phone     VARCHAR(50),
    customer_address   TEXT,
    items              JSONB            NOT NULL DEFAULT '{}',
    total_amount       NUMERIC(12, 2),
    currency           CHAR(3)          NOT NULL DEFAULT 'USD',
    status             VARCHAR(50)      NOT NULL DEFAULT 'New',
    created_at         TIMESTAMPTZ      NOT NULL DEFAULT NOW(),
    updated_at         TIMESTAMPTZ      NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_orders_external_provider_id
    ON orders (external_provider_id);

CREATE INDEX IF NOT EXISTS idx_orders_status
    ON orders (status);
"""

# --------------------------------------------------------------------------
# New "whatsapp_phone_orders" table — bot-generated orders (Gowtham B task).
# --------------------------------------------------------------------------
WHATSAPP_PHONE_ORDERS_CREATE_SQL = r"""
CREATE TABLE IF NOT EXISTS whatsapp_phone_orders (
    id                      BIGINT           GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    external_provider_id    VARCHAR(255)     NOT NULL UNIQUE,
    order_source            VARCHAR(50)      NOT NULL DEFAULT 'whatsapp',
    restaurant_id           BIGINT,
    customer_phone          VARCHAR(50),
    customer_address        TEXT,
    items                   JSONB            NOT NULL DEFAULT '{}',
    total_amount            NUMERIC(12, 2),
    currency                CHAR(3)          NOT NULL DEFAULT 'USD',
    note                    TEXT,
    whatsapp_message_sid    VARCHAR(255),
    whatsapp_phone_number   VARCHAR(50),
    status                  VARCHAR(50)      NOT NULL DEFAULT 'PendingApproval',

    -- Foreign-key / link back to the canonical main orders table once the
    -- order has been matched/duplicated there.
    synced_to_orders_id     BIGINT,

    created_at              TIMESTAMPTZ      NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ      NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_whatsapp_phone_orders_status
        CHECK (status IN (
            'PendingApproval', 'Approved', 'Synced', 'Rejected'
        ))
);
COMMENT ON TABLE whatsapp_phone_orders IS
    'Bot-generated WhatsApp orders awaiting manual approval before sync.';

CREATE INDEX IF NOT EXISTS idx_whatsapp_phone_orders_external_provider_id
    ON whatsapp_phone_orders (external_provider_id);

CREATE INDEX IF NOT EXISTS idx_whatsapp_phone_orders_status
    ON whatsapp_phone_orders (status);
"""

# Reference migration header + body (PostgreSQL). Handy for the migration
# runner; the raw CREATEs above are wired directly by the adapter.
WHATSAPP_PHONE_ORDERS_MIGRATION_SQL = r"""
-- 001_whatsapp_phone_orders.sql
-- Gowtham B: Integrate WhatsApp orders into the main orders table.
-- (See: Vancel Workspace task 361682aa-c03d-46d2-93ac-ac5352cd89ce)
BEGIN;

CREATE TABLE IF NOT EXISTS whatsapp_phone_orders (
    id                      BIGINT           GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    external_provider_id    VARCHAR(255)     NOT NULL UNIQUE,
    order_source            VARCHAR(50)      NOT NULL DEFAULT 'whatsapp',
    restaurant_id           BIGINT,
    customer_phone          VARCHAR(50),
    customer_address        TEXT,
    items                   JSONB            NOT NULL DEFAULT '{}',
    total_amount            NUMERIC(12, 2),
    currency                CHAR(3)          NOT NULL DEFAULT 'USD',
    note                    TEXT,
    whatsapp_message_sid    VARCHAR(255),
    whatsapp_phone_number   VARCHAR(50),
    status                  VARCHAR(50)      NOT NULL DEFAULT 'PendingApproval',
    synced_to_orders_id     BIGINT,
    created_at              TIMESTAMPTZ      NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ      NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_whatsapp_phone_orders_status
        CHECK (status IN ('PendingApproval', 'Approved', 'Synced', 'Rejected'))
);

COMMENT ON TABLE whatsapp_phone_orders IS
    'Bot-generated WhatsApp orders awaiting manual approval before sync.';

CREATE INDEX IF NOT EXISTS idx_whatsapp_phone_orders_external_provider_id
    ON whatsapp_phone_orders (external_provider_id);

CREATE INDEX IF NOT EXISTS idx_whatsapp_phone_orders_status
    ON whatsapp_phone_orders (status);

COMMIT;
"""

# --------------------------------------------------------------------------
# SQLite-compatible variants (used by tests / local dev only).
# --------------------------------------------------------------------------
WHATSAPP_PHONE_ORDERS_CREATE_SQLITE = r"""
CREATE TABLE IF NOT EXISTS whatsapp_phone_orders (
    id                      INTEGER          PRIMARY KEY AUTOINCREMENT,
    external_provider_id    TEXT             NOT NULL UNIQUE,
    order_source            TEXT             NOT NULL DEFAULT 'whatsapp',
    restaurant_id           INTEGER,
    customer_name           TEXT,
    customer_phone          TEXT,
    customer_address        TEXT,
    items                   TEXT             NOT NULL DEFAULT '{}',
    total_amount            NUMERIC,
    currency                TEXT             NOT NULL DEFAULT 'USD',
    note                    TEXT,
    whatsapp_message_sid    TEXT,
    whatsapp_phone_number   TEXT,
    status                  TEXT             NOT NULL DEFAULT 'PendingApproval',
    synced_to_orders_id     INTEGER,
    created_at              TIMESTAMP        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at              TIMESTAMP        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT chk_whatsapp_phone_orders_status
        CHECK (status IN ('PendingApproval', 'Approved', 'Synced', 'Rejected'))
);
CREATE INDEX IF NOT EXISTS idx_whatsapp_phone_orders_external_provider_id
    ON whatsapp_phone_orders (external_provider_id);
CREATE INDEX IF NOT EXISTS idx_whatsapp_phone_orders_status
    ON whatsapp_phone_orders (status);
"""

MAIN_ORDERS_CREATE_SQLITE = r"""
CREATE TABLE IF NOT EXISTS orders (
    id                 INTEGER    PRIMARY KEY AUTOINCREMENT,
    external_provider_id TEXT     UNIQUE,
    restaurant_id      INTEGER    NOT NULL,
    customer_name      TEXT,
    customer_phone     TEXT,
    customer_address   TEXT,
    items              TEXT       NOT NULL DEFAULT '{}',
    total_amount       NUMERIC,
    currency           TEXT       NOT NULL DEFAULT 'USD',
    status             TEXT       NOT NULL DEFAULT 'New',
    created_at         TIMESTAMP  NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at         TIMESTAMP  NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_orders_external_provider_id ON orders (external_provider_id);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders (status);
"""

