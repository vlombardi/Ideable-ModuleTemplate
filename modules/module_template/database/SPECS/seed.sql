-- module_template Seed Data
-- This file is optional. Add initial data for your module here.
-- It runs after the migrations have applied the schema, and after authorization.yaml.
-- Idempotent INSERTs recommended (ON CONFLICT DO NOTHING).

-- One `items` row and one related `sub_items` row, in the default tenant — so the worked example
-- (StandardEntityPage's master/detail composition, an-entity-is-served-by-the-framework-unless-
-- it-says-otherwise, sub-set 7) has something to show on a fresh installation instead of an empty
-- table. `name` is unique-enough by construction here (a fixed seed string), so `WHERE NOT EXISTS`
-- is the idempotency guard rather than a database constraint that does not exist on this column.
INSERT INTO template_items (tenant_id, name, description)
SELECT 1, 'Sample Item', 'A sample template item, seeded so the example has something to show'
WHERE NOT EXISTS (SELECT 1 FROM template_items WHERE name = 'Sample Item');

-- `WHERE NOT EXISTS` leads the clause deliberately: `scripts/dev/common/validate_modules.sh`'s
-- idempotency gate looks for that literal phrase, and a leading `AND NOT EXISTS` (with the join
-- condition first) reads identically to Postgres but not to that check.
INSERT INTO sub_items (tenant_id, item_fk, name, description)
SELECT 1, item.id, 'Sample Sub-Item', 'A sample sub-item, related to the item above by item_fk'
FROM template_items item
WHERE NOT EXISTS (SELECT 1 FROM sub_items WHERE name = 'Sample Sub-Item')
  AND item.name = 'Sample Item';
