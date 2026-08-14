**IMPORTANT**: define here module-specific backend specifications.

For the framework-wide audit trail contract (versioning, history endpoints, association
versioning, actor injection, frontend rendering rules) see:
`modules/module_template/SPECS/ideable-framework-specs/audit-trail-specs.md`

---

## Audit Trail — Module-Specific Configuration

Every entity model in this module must opt in to SQLAlchemy-Continuum versioning by default.
Association tables linking versioned entities must also apply `Versioned`.

**Versioned entities for the `template` baseline module:**
- `template_items` — main entity, full field-change versioning
- Any association tables linking `template_items` to other versioned entities

To opt out of versioning for a specific model:

```python
class SomeTransientModel(Base):
    __versioned__ = {'exclude': True}
    ...
```

**Permission used for all `/history` endpoints in this module:**
`require_permission('template.audit_trail:view')` — the fully-qualified
`<module_slug>.<resource>:<action>` form (see `general_bug_avoider.md` and the framework
`ideable-framework-specs/shared-backend-bug-avoider.md` § *Authorization*). A bare
`audit_trail:view` never matches the runtime permission set and always 403s.
