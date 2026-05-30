> **NOTE**: This file should not be changed since its content is inherited from the Ideable Framework ModuleTemplate and is updated via the `sync-template-updates.sh` script. For module-specific frontend specifications, use the `module-ui-specs.md` file.

---

## Main entities definition
A main entity is an entity that is not a sub-entity of another entity.

Association entities are not included in the navigation menu.

For each main entity defined in the backend (e.g., Users, Projects, Services, Automations, Digital Shelters, Variables, etc.), there must be a page in the frontend that allows the user to:
- view all the records of the entity in a table
- create a new record of the entity
- update an existing record of the entity
- delete an existing record of the entity

If not specified otherwise, all main entities must have a specific entity page defined.

Rule: it is assumed that the needed backend endpoints are already implemented and available. If, during the implementation of the entity page, some backend endpoint (e.g., entity create, read, update, delete) appears not to be implemented or available, this must be notified to the implementing agent.

## Entity page layout (general rule)

For every entity page, the content must be composed **top-to-bottom** as follows:

1. **Main entity** table.
2. When a row is selected, a **details card** for the selected entity must be rendered below the table.
3. A **visit mode** toggle with the two options
  - Depth visit
  - Full perspective
4. A **single tabs strip** (horizontal menu) that drives which association table is rendered.
5. Exactly **one association table** (FK or M2M) rendered below the tabs strip (based on the active tab).

Rule: At any time, the page must show:
- The main entity table.
- At most one association table (the one selected by the tabs strip).

### Details card requirements

When an entity is selected in the main table (the one that represents the entity type of the current page), the details card must:
- Show **all entity attributes**, including those not shown in the main table.
- the selected entity name must be highlighted in the details card (e.g. with a border or a different background color).
- Be future-proof: if new attributes are added later (e.g., image/avatar), the card is the intended place to show them.
- Use a **dense responsive grid** instead of a single vertical stack.
- Prefer **multiple fields per row** on medium and large screens.
- Allocate width **proportionally to the expected content length**:
  - short identifiers and metadata such as `name`, `code`, `id`, `type`, `status`, `creator`, `updater`, and FK references should stay compact,
  - long-text fields such as `description`, `notes`, `summary`, `comment`, and similar narrative values should span a wider portion of the card.
- Preserve vertical breathing room for long text fields so they can wrap naturally without making the whole card feel sparse.
- If a page needs a non-default width, the field definition may provide an explicit span hint (for example `gridSpan: 8` or `gridSpan: 12`).

Recommended implementation pattern:
- Render the details card as a **12-column responsive grid**.
- Default compact fields to about one third of the row width.
- Render description-like fields wider than short reference fields.
- Keep the card visually balanced with rounded borders, subtle background contrast, and clear label/value separation.

### Depth visit vs Full perspective

Depending on the visit mode toggle, the association table will show:
- In **"Depth visit"** mode: each tab in the tab strip, going left to right will visualize the entities related to the entity selected at the previous tab.
- In **"Full perspective"** mode: each tab in the tab strip will visualize all associated entities that are some way related to the selected main entity.

In "Depth visit" mode:
- Tabs are **static entity-type tabs** for each depth level (e.g., Profiles, Roles, Permissions).
- Deeper tabs that depend on an upstream selection must be **disabled** until that upstream selection exists.
- When an upstream selection changes, the downstream tab labels must be updated to reflect the current breadcrumb context.

For instance, let's consider a datamodel where a User can have multiple Profiles and a Profile can have multiple Roles and a role can have multiple Permissions. Let's assume we are in the "Users" page.
- Depth visit:
  - if the user selects a user (e.g., sadmin) in the Users table, then:
    -  the tabs strip will contain the following tabs:
      - "User: sadmin -> Profiles", containing the Profiles table showing all the Profiles associated with the user sadmin. Then, when the user selects a Profile (e.g., admin)), the Roles tab label is updated to: 
        - "User: sadmin -> Profile: admin -> Roles", containing the Roles table showing all the Roles associated with the profile admin. Then, when the user selects a Role (e.g., users_manager), the Permissions tab label is updated to: 
          - "User: sadmin -> Profile: admin -> Role: users_manager", containing the Permissions table showing all the Permissions associated with the role users_manager.
- Full perspective:
  - if the user selects a user (e.g., sadmin) in the Users table, then:
    -  the tabs strip will contain the following tabs:
      - "User: sadmin -> Profiles", containing all the Profiles for the user sadmin.
      - "User: sadmin -> Roles", containing all the Roles for all the Profiles associated with the user sadmin. The table will contain the columns "Profile" and "Role" and the Profile column will only show Profiles associated with the user sadmin.
      - "User: sadmin -> Permissions" containing all the Permissions for all the Roles for all the Profiles associated with the user sadmin. The table will contain the columns "Profile", "Role" and "Permission" and the Profile column will only show Profiles associated with the user sadmin.

### Tabs strip
(Association navigation and breadcrumb tabs)

The **tabs strip** must always be visible and must act as the user-controlled switch for the association table below.

Rules:
- Tab labels must be **breadcrumbs** describing the current context in terms of entities and selection chain.
- Tabs may represent direct associations (e.g., `Entity A -> Bs`) and deeper reachable associations (e.g., `Entity A -> B:<selected> -> Cs`).
- Deeper tabs that depend on an upstream selection must be **disabled** until that upstream selection exists.
- Selecting a row in the currently visible association table may:
  - Set the upstream selection for the next level.
  - Automatically switch the active tab to the next-level association tab.

#### Tab mounting vs counters (user-controlled visibility)
When a main entity row is selected and a tab strip shows multiple association sub-tables:
- The user must control what is rendered by clicking the tab (tab content must be lazy-mounted; do not force-mount all tabs).
- Tab counters (e.g. `Permissions (12)`) must update immediately on selection even if the tab has not been opened.

Implementation guideline:
- Use lightweight "count queries" (e.g. request `limit=1`) to fetch just the `total` for each association and update the tab labels.
- The full table data query for a tab should be enabled only when that tab is active.

#### Selection validity and pruning

When the upstream selection changes, downstream selections must be preserved **only if still valid**.

Rules:
- If a selected downstream item is no longer reachable under the new upstream selection, it must be cleared automatically.
- When pruning clears the selection required for the currently active tab, the UI must automatically switch back to the nearest valid tab.

---

## Shared Components and Table Infrastructure

### Required Shared Components

If not specified otherwise, every module MUST include the following shared components in `src/components/`:

#### ServerDataTable Component

**File:** `src/components/ServerDataTable.tsx`

**Purpose:** Reusable data table with server-side pagination, sorting, and filtering.

**Requirements:**
- Must use CSS prefix `${prefix}` matching the module slug (e.g., `template`)
- Must include proper spacing between all elements
- Must have separate header rows for sorting and filtering
- Must support audit column toggling

**Implementation Pattern:**
```typescript
// Key structure:
<thead className="${prefix}-bg-muted">
  {/* Row 1: Sort headers */}
  <tr className="${prefix}-border-b">
    {columns.map(column => (
      <th>
        <button onClick={() => handleSort(column.id)}>
          <span>{column.header}</span>
          <span>{getSortIcon(column.id)}</span>
        </button>
      </th>
    ))}
  </tr>
  {/* Row 2: Filter inputs */}
  <tr className="${prefix}-border-b">
    {columns.map(column => (
      <th>
        {getFilterInput(column)}
      </th>
    ))}
  </tr>
</thead>
```

**CSS Requirements:**
- Table wrapper: `${prefix}-border ${prefix}-rounded-md ${prefix}-overflow-hidden`
- Header row spacing: `${prefix}-px-4 ${prefix}-py-3` for headers, `${prefix}-px-4 ${prefix}-py-2` for filters
- Pagination: `${prefix}-flex ${prefix}-items-center ${prefix}-justify-between ${prefix}-gap-2`
- Action buttons in header: `${prefix}-flex ${prefix}-items-center ${prefix}-gap-4`

#### Component Directory Structure

```
src/components/
├── ServerDataTable.tsx    # Required - main table component
├── ui/                    # Optional - UI primitives if not using HostApp's
│   ├── button.tsx
│   ├── input.tsx
│   └── checkbox.tsx
```

#### UnsavedChangesDialog Component

**File:** `src/components/UnsavedChangesDialog.tsx`

**Purpose:** Shared confirmation dialog for pages that have unsaved edits.

**Requirements:**
- Must be used together with `useUnsavedChangesGuard` for any page that supports create/edit flows.
- Must expose the three standard actions when available:
  - keep editing
  - discard changes
  - save changes
- Must reuse the common labels defined in the translation files:
  - `common.unsavedChangesTitle`
  - `common.unsavedChangesMessage`
  - `common.keepEditing`
  - `common.discard`
  - `common.save`
- Must remain scoped to the module root and must not alter HostApp global selectors.

**Implementation note:**
- The component is intentionally small and page-agnostic.
- Page-specific behavior belongs in the `useUnsavedChangesGuard` action callbacks, not inside the dialog.

---

## Tables

Every UI table must:
- have a **header** in which every column is sortable via an icon on the right of the column name, or equivalently clicking on the column name. The icon must change to represent whether the column is:
  - the **sorting column**, in which case the icon will be a down or up arrow, coherently with the sorting order
  - not the sorting column, in which case it will be a up&down arrow
  - Sort icons: Unsorted `↕`, Ascending `↑`, Descending `↓`
- for columns containing text, below the column name, the table header presents an input text field whose purpose is **filtering** the contents of the table. The string input by the user must be considered as a sub-string of the searched field. If "thing" is input, then all the records that contain "thing" in the text are shown in the table (so a record whose related column content is "this is a thing to consider" is shown).
- for columns containing boolean, below the column name, the table header presents a **Select dropdown (All / True / False)** whose purpose is **filtering** the contents of the table.
- **Boolean filter normalization**: Boolean filters must work regardless of how the boolean is rendered by the UI or client. The backend must accept the following values for boolean filter query params:
  - True-ish: `true`, `t`, `1`, `yes`, `y`, `on` (case-insensitive)
  - False-ish: `false`, `f`, `0`, `no`, `n`, `off` (case-insensitive)
  - Empty / missing: means "no filter"
- have all the usual elements for **server-side pagination** like:
  - (above the table, on the left) the number of elements per page (specifying how many records to show inside the table)
  - (below the table, on the right), from left to right:
    - **First Button** (to go directly on the first page)
    - **Previous button** (disabled when in the first page)
    - the **page number** on the **total** (e.g., "3 of 110" to inform the user that the current page is the third on a total of 110 pages)
    - **Next button** (disabled when in the last page)
    - **Last Button** (to go directly on the last page)

- **Column filter rendering**: Filter inputs must only be rendered for data columns. The row-selection checkbox column (id `__select__`) and the actions column (id `actions`) must not render any filter input. Boolean columns must render a Select dropdown (All / True / False); all other data columns render a text input.

- **Empty filter params**: When a filter is cleared (empty value), the corresponding query parameter must be omitted entirely from the API request — never sent as an empty string. Sending an empty string for a boolean or typed parameter will cause a 422 from the backend.

- **Sticky Header & Responsive Layout**: Table headers must remain fixed ("sticky") at the top during vertical scrolling. The table structure should adapt fluidly to different screen sizes. The footer should stick to the bottom of the available viewport, with only the table's body content being scrollable.

- **Row deselection**: When a row in a table is selected and the user clicks on the area containing that table but outside the table itself, the selected row should be deselected.

- **audit columns**: On the right of the table title there should be a flag "Show audit data" that when selected make the table show as last columns before the action column the audit columns (created_at, updated_at, deleted_at) if they exist in the table. The actual audit column names in the backend are au_creation_timestamp, au_last_update_timestamp, au_created_by_user, au_last_updated_by_user.
  - For association sub-tables (M2M tables rendered below a selected row), the same toggle must be available and must work even if the page did not explicitly include audit columns in the table column definitions. The association table component must append the standard audit columns automatically so the toggle always reveals audit data when it exists in the API response.

- **Column Header Naming**: Column headers should be user-friendly with the following naming conventions:
  - Audit columns: "Au Creation Timestamp" → "Created At", "Au Last Update Timestamp" → "Updated At", "Au Created By User" → "Creator", "Au Last Updated By User" → "Updater"
  - Foreign key columns: Remove "_fk" suffix and capitalize (e.g., "Project FK" → "Project", "Scope FK" → "Scope", "Digitalshelter FK" → "Digital Shelter")
  - General formatting: Capitalize words and replace underscores with spaces

- **Column sizing (ID/FK)**: To maximize the space for "talking" columns (e.g. name, description), `id` and `*_fk` columns must use the minimum practical horizontal space.
  - Apply a narrow fixed width to header, filter cell, and body cells for:
    - `id`
    - any column whose id/accessor ends with `_fk`
  - These columns must be `whitespace-nowrap` and should not expand to fill available width.
  - "Talking" columns should be allowed to take the remaining width.
  - Narrow-column headers must not overlap adjacent headers. Narrow header cells must clip overflow.
  - Narrow-column header labels must avoid ellipses. Prefer abbreviated labels with a dot suffix (e.g. `Assignment ID` -> `Ass. ID`, `Profile FK` -> `Prof. FK`) and provide a tooltip (e.g. native `title`) that shows the full header label on hover.
  - Do not reduce font size or sorting icon size for narrow columns; keep consistent sizing across all headers.

- **Coherent width by data type**: Every table must reserve horizontal space in a way that matches the content type.
  - `id` columns should stay minimal, sized just enough to show the header and a short numeric identifier.
  - Name-like columns should be wider than `id`, but narrower than descriptive text columns.
  - Description / notes / long-text columns should receive the widest default space.
  - Boolean, code, status, and other compact fields should remain relatively narrow.
  - These are default widths only: users must be able to resize columns when needed.

- **Resizable columns**: All data columns must support user-driven horizontal resizing.
  - Resizing must be available directly from the table header area.
  - Resizing should preserve a coherent table layout: compact columns stay compact by default, but users may expand or shrink them.
  - On first render, columns should auto-fit to the current header and cell content as much as practical, while still respecting the per-column default and minimum width rules.
  - After the initial auto-fit, the table should continue to follow the data-type-based width policies and preserve any manual user resizing.
  - The table should also stretch to fill the available horizontal space inside the content panel; content-based sizing should act as the minimum width, not the final maximum width.
  - The implementation may keep widths local to the table instance; persistence across page reloads is optional unless explicitly requested.

- **Overflow handling**: When a header or cell does not fit in the available width, the rendered content must use ellipsis truncation instead of clipping away the last characters.
  - Truncated text must expose the full content via a tooltip (for example, the native `title` attribute).
  - This applies to table headers and body cells, including FK reference displays.
  - Non-textual cells (for example action buttons or custom controls) may opt out of ellipsis behavior when truncation would break the interaction.

- **Referenced entity IDs as suffix (and suppress referenced id/FK columns)**:
  - When a table cell represents a reference to another entity (e.g., User/Profile/Role/Permission), the UI must display the referenced entity id as a suffix in parenthesis after the entity "talking" name:
    - Display format: `<name> (<id>)`
    - Examples: `admin (1)`, `PowerUsers (3)`, `users.read (10)`
  - Primary name field used for references:
    - User: `username`
    - Profile: `profile`
    - Role: `role`
    - Permission: `name`
  - Missing data:
    - If the name is missing but `id` exists: display `(<id>)`
    - If `id` is missing: display `-`
  - Column suppression rule (references only): in any table where a referenced entity is displayed via a "talking" column (e.g., `Username`, `Profile`, `Role`, `Permission`), the UI must not show separate columns for:
    - the referenced entity `id` column (if present), and
    - referenced entity FK columns (e.g., `user_fk`, `profile_fk`, `role_fk`, `permission_fk`).
    - The "talking" column is the canonical display and must include the `(<id>)` suffix.
  - Filtering behavior for suffix IDs (substring model):
    - Filtering on a referenced-entity "talking" column must support substring matching on the name AND filtering by referenced id when the filter contains an id token in parentheses.
    - Define an ID token as any substring matching the pattern: `\(\d+\)` (example: `(10)`).
    - Filter evaluation rules:
      - If the filter contains exactly one ID token, the row must match the referenced id token (i.e., referenced entity `id` equals the token number).
      - If the filter contains multiple ID tokens, treat the filter as a normal substring filter (no special id parsing).
      - If the filter contains additional text besides the ID token(s), the referenced entity name must also match that text using the normal substring filter semantics (case-insensitive).
      - If the filter contains no ID tokens, apply the normal substring filter semantics on the referenced entity name.
    - Examples:
      - Filter value `(10)` matches rows where referenced entity id is `10`.
      - Filter value `admin (10)` matches rows where referenced entity id is `10` and referenced entity name contains `admin`.

### Entity List Page Requirements

Every entity list page MUST:

1. **Use ServerDataTable component** - Never use raw `<table>` elements
2. **Define proper column definitions** with ColumnDef interface:
   ```typescript
   const columns: ColumnDef<EntityType>[] = [
     { id: 'id', header: 'ID', accessorKey: 'id', meta: { sortable: true } },
     { id: 'name', header: 'Name', accessorKey: 'name', meta: { sortable: true } },
     { id: 'actions', header: 'Actions', cell: renderActions, meta: { sortable: false } },
   ]
   ```
3. **Include audit columns** with proper formatting:
   ```typescript
   {
     id: 'au_creation_timestamp',
     header: 'Created At',
     accessorKey: 'au_creation_timestamp',
     cell: ({ row }) => formatTimestamp(row.getValue('au_creation_timestamp')),
     meta: { sortable: true }
   }
   ```
4. **Provide header actions** via the `actions` prop (Create button, etc.)
5. **Handle audit toggle** via `showAuditColumns` and `onToggleAuditColumns` props

#### Layout Requirements

**Header Section:**
```
[Title]                           [Audit Toggle] [Create Button]
```
- Must use `${prefix}-flex ${prefix}-items-center ${prefix}-justify-between`
- Must have `${prefix}-gap-4` or `${prefix}-gap-6` between header controls
- Title must use `${prefix}-text-2xl ${prefix}-font-bold`
- Entity pages must render a single visible title only: the page-level `h1` is the canonical title and the `ServerDataTable.title` prop must be omitted when it would duplicate that heading

**Table Section:**
```
Rows per page: [10 ▼]

┌─────────────────────────────────────────────────────────────┐
│ ID ↕    │ Name ↕    │ Description ↕    │ Actions          │  <- Sort row
│ [____]  │ [______]  │ [____________]   │                  │  <- Filter row
├─────────┼───────────┼──────────────────┼──────────────────┤
│ 1       │ Item A    │ Description...   │ [Edit] [Delete]  │
└─────────────────────────────────────────────────────────────┘

[First] [Previous]  1 of 10  [Next] [Last]          Showing 1 to 10 of 100 results
```

**Spacing Rules:**
- Page title margin: `${prefix}-mb-6`
- Between create form and table: `${prefix}-space-y-4`
- Between filter inputs and header labels: consistent gap (use flex-col with gap)
- Pagination button spacing: `${prefix}-gap-2`
- Action buttons in rows: `${prefix}-gap-2`

### CSS/Tailwind Requirements for Tables

#### Prefix Convention
- All CSS classes MUST use the module's slug prefix `${prefix}-` (e.g., `template-`)
- Never mix prefixes between modules
- Never use unprefixed Tailwind classes

#### Required Classes for Tables

**Table Container:**
- `${prefix}-border ${prefix}-rounded-md ${prefix}-overflow-hidden`

**Header Row:**
- Container: `${prefix}-bg-muted`
- Sort header cells: `${prefix}-px-4 ${prefix}-py-3 ${prefix}-text-left ${prefix}-font-semibold ${prefix}-text-sm`
- Filter row cells: `${prefix}-px-4 ${prefix}-py-2`

**Body Rows:**
- Cells: `${prefix}-px-4 ${prefix}-py-2`
- Hover: `hover:${prefix}-bg-muted/50`
- Selected: `${prefix}-bg-muted`

**Pagination:**
- Container: `${prefix}-flex ${prefix}-items-center ${prefix}-justify-between ${prefix}-py-2`
- Buttons: `${prefix}-px-3 ${prefix}-py-1 ${prefix}-border ${prefix}-rounded-md disabled:${prefix}-opacity-50`

### Edit mode for tables

When in edit mode:
- **Edit and Delete Buttons**: every table row must include an "Edit" button and a "Delete" button. The "Edit" button should open a modal or a dedicated page to modify the record, while the "Delete" button should trigger a confirmation dialog before removing the record.

- **Modal Field Requirements**: Create and edit modals must include ALL available entity fields (excluding auto-generated audit data):
  - All foreign key fields must use the **Entity Selector Pattern**: display as `"<Name> (<ID>)"` with a "Select" button opening a modal containing a canonical ServerDataTable (sorting, filtering, server-side pagination). Never use raw integer inputs or simple dropdowns.
  - Boolean fields should be checkboxes
  - Text fields should be text inputs
  - JSON fields should be textarea inputs with JSON validation
  - Code fields should be textarea inputs with monospace font
  - Example: Entity modals must include all entity fields such as enabled, status, related_entity_fk, and category_fk in addition to name and description

- **Form layout requirements**: Create and edit forms must use a **dense responsive 12-column grid** instead of a single vertical stack.
  - Prefer **multiple fields per row** on medium and large screens.
  - Keep short fields compact: `name`, `code`, `id`, `type`, `status`, `creator`, `updater`, FK references, and simple booleans should usually occupy about one third of the row.
  - Give narrative fields more room: `description`, `notes`, `summary`, `comment`, `address`, and similar long values should span a wider portion of the grid and use taller textareas when appropriate.
  - Use explicit span hints when a field needs a non-default width, for example `gridSpan: 6`, `gridSpan: 8`, or `gridSpan: 12`.
  - Keep controls visually balanced with rounded cards, subtle background contrast, consistent internal padding, and clear label/value separation.
  - Preserve validation behavior: required fields remain required, and checkbox/entity-selector controls must keep their original semantics.

- **Bulk Delete**: The table should include a bulk delete option that allows users to select multiple records and delete them at once. This should be implemented as a checkbox in the table header that, when checked, enables a "Delete Selected" button.

### Associated entities in tables

#### Foreign Key Columns
When an entity has a foreign key to another entity, the associated entity should be displayed in the table as a link to the associated entity page. When the user clicks on the link, the user should be redirected to the associated entity page.
When in edit mode, FK fields must use the **Entity Selector Pattern** (see Edit mode section above) — never dropdown menus.

#### Many-to-Many Relationships
When an entity of type A has a many-to-many relationship with entities of type B (refer to openapi.yaml for the definition of the relationships), the page that lists the A entities as a table should have a tab section below the table to display the B entities in the related table (the same table view used when entity B is selected from the sidebar).

**M2M relationships are bidirectional**: if the A page shows a tab for B, then the B page must also show a tab for A. Both sides of every M2M association must be represented in the UI — there is no "owning side" from a UI perspective.

If an entity of type A has relations with more than one entity, let's say of types B, C, and D, then the table for entities of type A should have one tab section for each entity type (B, C, and D), and each tab section should contain a table to show the entities of the related entity type.

When the user selects a row in the table for entity type A, and in the tab list below is selected the tab for entity type B, then the table for entity type B should be filtered to show only the entities of type B that are related to the selected entity of type A.

When in edit mode, and a row in the table for entity type A is selected, then if the user:
- deletes an entity in the table inside the tab for entity type B, then the association between the selected entity of type A and the deleted entity of type B should be removed.
- adds an entity in the table inside the tab for entity type B, then the association between the selected entity of type A and the added entity of type B should be created.

##### Add button on association tables (normative)

When in **edit mode**, every association table (M2M sub-table under a selected main entity) **must** display an **"Add <EntityType>"** button in the table header toolbar (left side, next to the table title).

**Requirements:**
1. **Visibility**: The button only appears when:
   - The page is in edit mode
   - A main entity row is selected
   - The association tab is active

2. **Button behavior**: Clicking the button opens a modal containing:
   - A canonical ServerDataTable showing all available entities of type B
   - Entities already associated with the selected entity A must be excluded (or marked as disabled)
   - User selects an entity to create the association

3. **Button labeling**: Use the pattern `"Add <EntityType>"` (e.g., "Add Risk Aspect Group", "Add Permission")

4. **Layout**: Follow the standard table header layout:
   ```
   [Add <EntityType> Button]          [Audit Toggle]
   ```

##### Unlink action icon
The action button to remove an association in a M2M sub-table must use an **unlink icon** (broken chain, e.g. `Unlink` from lucide-react), not a generic delete/close icon (`X` or `Trash2`). This visually distinguishes "remove association" from "delete record".

#### Speaking columns: server-side sorting/filtering via dotted paths
In association sub-tables, the UI must allow sorting and filtering on "speaking" columns that come from related entities (e.g. Permission Name, Role Name, Username), not just the raw FK fields.

Rules:
- The column `id` used for server sorting/filtering must be the dotted path (e.g. `permission.name`, `role.role`, `user.username`).
- The backend must accept:
  - `sort_by=<dotted>` and `sort_order=asc|desc`
  - `filters=<json>` where `<json>` is a JSON object string whose keys are dotted paths
- The frontend must never send dotted filter keys as raw query params. All dotted filters go into the single `filters` JSON string query param.

#### Constrained FK columns must be non-sortable/non-filterable
If a FK column is constrained by the current selection in the parent table (e.g. `role_fk` in the permissions-for-selected-role table), it must be marked `meta.sortable=false` and `meta.filterable=false`.

#### Column header labels in association tables
Column ids may be technical (including dotted paths). User-facing header text must remain stable and readable.

Rules:
- If the table column definition provides a string `header` (e.g. `header: "Name"`), that string must be used for the header label.
- Dotted ids must not leak into the UI as header labels (avoid showing `permission.name` to users).

#### Editable association attributes
Every attribute that belongs to the association itself (i.e. a column of the join table, not of the associated entity) must be **inline-editable** directly in the sub-table row when in edit mode:
- `boolean` → render a togglable checkbox or toggle switch; clicking it immediately PATCHes the association.
- `string` / `text` → render an inline text input that commits on blur or Enter.
- `integer` / `numeric` → render an inline number input that commits on blur or Enter.
- `enum` / `select` → render an inline Combobox dropdown that commits on selection.

Attributes of the associated entity (not the join table) remain read-only in the association sub-table.

#### Conditional disabling of association attribute controls
When a business constraint prevents changing an association attribute for a specific record, the inline control must be **disabled** (`disabled` attribute, `cursor-not-allowed`, reduced opacity) and must show a **tooltip** (`title`) explaining why, including the name of the blocking entity when available.

When the constraint does **not** apply to a record (i.e. the change is allowed), the control must be **fully editable** in edit mode — it must not be disabled or read-only.

**Critical**: the disabling condition must be based on the **presence of a blocking entity**, not on the current value of the attribute alone. For example, a `boolean` attribute with value `false` does not by itself mean the control should be disabled — it should only be disabled if another entity is actively blocking the change. If no blocking entity exists, the control must be enabled regardless of the current attribute value.

Example: a `boolean` attribute that enforces a single-owner constraint (only one A entity can hold the attribute as `true` for a given B entity) must be rendered as a disabled checkbox **only when another A entity already holds `true` for that B** (i.e. a blocking entity name is present in the response). The tooltip must read `<attribute label>: <name of the blocking A entity>`. When no other A entity holds `true` for that B (blocking entity name is absent), the checkbox must be **enabled and togglable**, even if the current value is `false`.

To support this, the backend GET endpoint for the M2M association must return sufficient context alongside each constrained attribute — i.e. the name (or identifier) of the entity that is currently blocking the change, so the frontend can display it in the tooltip without making additional requests.

---

## Human-readable entity references (normative)

For every entity B associated with an entity A (i.e., B's id is linked as a foreign key to A, or A and B ids are inside an association table in the datamodel), the UI must render references as **"<Name> (<ID>)"** — never as raw IDs alone.

### Column headers (translation keys → human-readable labels)

Column headers displayed to users must be **human-readable labels**, not translation key paths:

| Incorrect | Correct |
|-----------|---------|
| `entities.columns.entityType` | **Entity Type** |
| `ENTITY.COLUMN.TYPE` | **Entity Type** |
| `entity_type_fk` | **Entity Type** |
| `moduleEntity.columns.relatedGroup` | **Related Group** |

**Rule**: Use `t()` to resolve translation keys to human-readable strings. If the translation value itself looks like a code path, fix the i18n file — don't display the key.

### Table cell rendering for FK columns (talking columns)

When a table column represents a foreign key (e.g., `entity_type_fk`, `parent_fk`, `category_fk`), the cell must render as:

```
<ReferencedEntityName> (<ID>)
```

**Examples**:
- `Main Headquarters (5)` instead of `5`
- `Acme Corporation (12)` instead of `12`
- `Security Policy (3)` instead of `3`

**Implementation pattern**:
```typescript
// In ColumnDef, use a cell renderer for FK columns:
{
  id: 'entity_type_fk',
  header: t('entities.columns.entityType'), // resolves to "Entity Type"
  accessorKey: 'entity_type_fk',
  cell: (info) => {
    const relatedEntity = info.row.original._related?.entity_type;
    return relatedEntity ? `${relatedEntity.name} (${relatedEntity.id})` : info.getValue();
  },
  meta: { sortable: true, filterable: true }
}
```

**Backend requirement**: The API must support embedding related entities (e.g., `?embed=entity_type`) so the frontend can access `relatedEntity.name`.

### Details card rendering

In the **details card** (the panel showing the selected entity's attributes), FK fields must also render as `"<Name> (<ID>)"`:

```typescript
// Detail field example:
{
  id: 'entity_type_fk',
  label: t('entities.columns.entityType'), // "Entity Type"
  value: (item) => item._related?.entity_type
    ? `${item._related.entity_type.name} (${item._related.entity_type.id})`
    : item.entity_type_fk
}
```

### Summary rule

| Context | Raw ID | Human-Readable Reference |
|---------|--------|--------------------------|
| Table column header | `entity_type_fk` | **Entity Type** |
| Table cell value | `5` | **Main Headquarters (5)** |
| Details card label | `entity_type_fk` | **Entity Type** |
| Details card value | `5` | **Main Headquarters (5)** |
| Form field label | `entity_type_fk` | **Entity Type** |
| Form field value | `5` | **Main Headquarters (5)** |

---

## Form FK association selection (normative)

When a form contains a foreign key field (association to another entity), the UI must **never** display a raw integer input or a simple dropdown. Instead, use the **Entity Selector Pattern**:

### Display format
The currently selected entity must be shown as:
```
<ReferencedEntityName> (<ID>)
```
Example: `Security Assessment (3)` instead of just `3`.

### Selection mechanism
To change the association, provide a **"Select"** button next to the display. Clicking this button opens a **modal popup** containing:

1. **Canonical ServerDataTable** with:
   - Full column headers with sorting indicators
   - Per-column filtering inputs
   - Server-side pagination (not client-side)
   - Audit toggle for showing/hiding audit columns
   - All standard Ideable table features

2. **Selection interaction**:
   - Clicking a row selects that entity and closes the modal
   - The selected entity's name and ID populate the form field
   - The form tracks the ID for submission

3. **Cancel/Dismiss**:
   - Modal can be dismissed without selection (no change to form)

### Implementation pattern
```typescript
// Form field definition for FK association
{
  id: 'related_entity_fk',
  label: t('entities.columns.relatedEntity'), // "Related Entity"
  type: 'entity-select',
  entityDisplay: (item) => item._related?.related_entity
    ? `${item._related.related_entity.name} (${item._related.related_entity.id})`
    : '-',
  entityService: relatedEntityService, // Service to fetch list for modal
  entityColumns: relatedEntityColumns, // Columns for the selection table
  required: true,
}
```

### Why not dropdowns?
| Dropdown | Entity Selector |
|----------|-----------------|
| Loads all data client-side | Server-side paging, handles large datasets |
| No filtering capability | Full column filtering |
| No sorting | Multi-column sorting |
| Performance issues with >100 items | Scales to thousands of records |
| Shows only one field | Shows all relevant entity attributes |

### Backend requirement
The entity service used for selection must support standard `QueryParams` (pagination, sorting, filtering) and optionally `?embed=` for displaying related data in the selection table.

---

## Dropdowns

- All dropdown components must sort their items alphabetically in ascending order and include a search box to easily filter options.
- `Select.Item` (Radix UI) components must **never** use an empty string as a `value` prop — this causes a runtime error. Use a sentinel value (e.g., `"all"`, `"none"`) and translate it back to the appropriate internal state in the `onValueChange` handler.

## Dialog and Modal Styling

All dialogs and modals must have:
  - Overlay background: `bg-black/80` (semi-transparent dark overlay)
  - Content background: `bg-white` (solid white background for readability)
  - No transparency or blur effects on the content area
  - Proper z-index layering to appear above other content
  - `DialogContent` must stay within the viewport and provide a vertical scroll area whenever the content height may exceed the screen

### Table-selection dialogs

Any modal used to choose an entity from a `ServerDataTable` or equivalent selection table must:

- Define a viewport-based maximum height
- Enable vertical scrolling on the dialog body/content
- Open with a horizontally resizable dialog surface that aims to fit the table's natural width
- Cap the dialog width at 90% of the viewport width
- Use horizontal scrolling inside the table area if the table still cannot fit within that cap
- Keep the table accessible without expanding the popup off-screen
- Preserve filtering, sorting, and server-side pagination behavior

---

## Migration Guide for Existing Modules

If a module has raw table implementations:

1. Create `src/components/ServerDataTable.tsx` (copy from ModuleTemplate)
2. Update entity pages to use `ServerDataTable` instead of raw `<table>`
3. Define proper `ColumnDef` arrays for each entity
4. Remove manual sorting/filtering/pagination logic
5. Test audit column toggle functionality
6. Verify spacing matches this specification

---

## Verification Checklist

Before considering a module complete:

- [ ] ServerDataTable component exists in src/components/
- [ ] All entity list pages use ServerDataTable (no raw `<table>` elements)
- [ ] Table headers have proper two-row structure (sort + filter)
- [ ] Pagination controls are properly spaced and functional
- [ ] Audit column toggle works and shows/hides audit columns
- [ ] Create button is in header with proper spacing
- [ ] No overlapping elements or crammed text
- [ ] Sort icons display correctly (↕, ↑, ↓)
- [ ] Filter inputs don't overlap with header text
- [ ] All spacing matches HostApp's visual standards
- [ ] CSS prefix is consistent throughout (e.g., `${prefix}-`)
