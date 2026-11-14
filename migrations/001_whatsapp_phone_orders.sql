# migrations/001_whatsapp_phone_orders.sql

-- 001_whatsapp_phone_orders.sql
-- Gowtham B: Integrate WhatsApp orders into the main orders table.
-- (Vancel Workspace task 361682aa-c03d-46d2-93ac-ac5352cd89ce)
-- Design recorded in the 2026-11-05 "Restaurant Ordering System" meeting:
--   * new `whatsapp_phone_orders` table stores bot orders (nullable columns,
--     `external_provider_id` is the UNIQUE key to link back to main orders)
--   * manual restaurant-manager approval before the order enters the kitchen
--   * backend "match and duplicate" pushes the order into the main orders table
--     (creates the main row if it doesn't already exist)

BEGIN;

CREATE TABLE IF NOT EXISTS whatsapp_phone_orders (
    id                      BIGINT           GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    external_provider_id    VARCHAR(255)     NOT NULL UNIQUE,
    order_source            VARCHAR(50)      NOT NULL DEFAULT 'whatsapp',
    restaurant_id           BIGINT,
    customer_name           VARCHAR(255),
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
