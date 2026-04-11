CREATE TABLE IF NOT EXISTS template_items (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    au_creation_timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    au_last_update_timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    au_created_by_user VARCHAR(100),
    au_last_updated_by_user VARCHAR(100)
);

CREATE INDEX IF NOT EXISTS idx_template_items_name ON template_items(name);
