-- ModuleTemplate authorization seed for HostApp RBAC
-- Idempotent by design: all inserts use ON CONFLICT DO NOTHING.

-- Profiles
INSERT INTO profiles (profile, description, au_created_by_user)
VALUES
    ('template_admin', 'ModuleTemplate administrators', 'system'),
    ('template_reader', 'ModuleTemplate read-only users', 'system')
ON CONFLICT (profile) DO NOTHING;

-- Roles
INSERT INTO roles (role, description, au_created_by_user)
VALUES
    ('template_items_manager', 'CRUD access to Template Items', 'system'),
    ('template_items_reader', 'Read access to Template Items', 'system')
ON CONFLICT (role) DO NOTHING;

-- Permissions for entity template_items
INSERT INTO permissions (name, description, resource, action, au_created_by_user)
VALUES
    ('template.items.read', 'Read template items', 'template.items', 'read', 'system'),
    ('template.items.create', 'Create template items', 'template.items', 'create', 'system'),
    ('template.items.update', 'Update template items', 'template.items', 'update', 'system'),
    ('template.items.delete', 'Delete template items', 'template.items', 'delete', 'system')
ON CONFLICT (name) DO NOTHING;

-- Role to permission mapping
INSERT INTO as_role_permission (role_fk, permission_fk, au_created_by_user)
SELECT
    (SELECT id FROM roles WHERE role = 'template_items_manager'),
    p.id,
    'system'
FROM permissions p
WHERE p.name IN (
    'template.items.read',
    'template.items.create',
    'template.items.update',
    'template.items.delete'
)
ON CONFLICT (role_fk, permission_fk) DO NOTHING;

INSERT INTO as_role_permission (role_fk, permission_fk, au_created_by_user)
SELECT
    (SELECT id FROM roles WHERE role = 'template_items_reader'),
    p.id,
    'system'
FROM permissions p
WHERE p.name = 'template.items.read'
ON CONFLICT (role_fk, permission_fk) DO NOTHING;

-- Profile to role mapping
INSERT INTO as_profile_role (profile_fk, role_fk, au_created_by_user)
VALUES
    (
        (SELECT id FROM profiles WHERE profile = 'template_admin'),
        (SELECT id FROM roles WHERE role = 'template_items_manager'),
        'system'
    ),
    (
        (SELECT id FROM profiles WHERE profile = 'template_reader'),
        (SELECT id FROM roles WHERE role = 'template_items_reader'),
        'system'
    )
ON CONFLICT (profile_fk, role_fk) DO NOTHING;

-- Ensure HostApp admin profile can manage ModuleTemplate out of the box
INSERT INTO as_profile_role (profile_fk, role_fk, au_created_by_user)
SELECT
    p.id,
    r.id,
    'system'
FROM profiles p
JOIN roles r ON r.role = 'template_items_manager'
WHERE p.profile = 'admin'
ON CONFLICT (profile_fk, role_fk) DO NOTHING;
