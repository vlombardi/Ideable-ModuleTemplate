import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import type { ColumnDef } from "@tanstack/react-table"
import { History as HistoryIcon, Pencil as PencilIcon, Trash2 as TrashIcon } from "lucide-react"
import { EntityTable } from "./EntityTable"
import { ServerDataTable } from "./ServerDataTable"
import { type PageResult } from "./AssociationServerDataTable"
import { useServerTableState } from "../hooks/useServerTableState"
import { useTranslation } from "../hooks/useTranslation"
import { AuditTrailPopup, type AuditPageParams, type VersionPage } from "./AuditTrailPopup"
import { useEntityQuery, type EntityTransport, type UseEntityQueryResult } from "../hooks/useEntityQuery"
import { useHostEditMode } from "../hooks/useHostEditMode"
import { EntityForm, type EntityFormField } from "./EntityForm"
import { RowActionButton, RowActions } from "./RowActionButton"
import { Button } from "../primitives/button"

/**
 * The standard master page for one declared entity: its table, and the audit trail behind it.
 *
 * A COMPONENT, NOT A ROUTE. It registers no path and assumes nothing about being full-screen, so
 * the caller decides where it appears — bound to a menu item, or opened from a module's own
 * navigation inside a popup, a drawer or a tab. A page that could only be a route could not be
 * reached from inside another screen, and "open this entity's table in a popup" is an ordinary
 * requirement rather than an exotic one.
 *
 * THE FIRST ENTRY IN THE STANDARD-PAGES CATALOGUE, and built to the three properties that make one:
 * it takes its subject as a parameter (`entityKey`), it does not own its placement, and it is
 * decomposed — `EntityTable` and `EntityForm` are exported separately, so a module writing its own
 * page reuses the parts instead of copying the whole. A sealed page would make the escape hatch a
 * fork, which is the failure this design exists to avoid.
 *
 * What it does NOT do is decide what an entity's columns mean. Labels, cell renderers and the
 * column order come from the caller, because they need translating and may need arbitrary React.
 */
/**
 * One field of the details card — `shared-ui-widgets-specs.md` § *The standard entity page*
 * → *The details card*.
 */
export interface DetailField<Row> {
  /** The row's property this field shows. */
  name: string
  /** Already translated — the page resolves its own chrome, not the module's copy. */
  label: string
  /** Optional renderer. Default: the value as text, or `-` when it is absent. */
  render?: (row: Row) => React.ReactNode
  /** 12-column grid span. Omit to let the page choose by the field's expected content length. */
  gridSpan?: number
  /**
   * This field holds the entity's NAME. Exactly one field of a declared card sets it; the page
   * renders it as the card's header, which is what says WHICH entity the card describes. The page
   * cannot know it — a module's datamodel is the module's — and must not guess.
   */
  isName?: boolean
}

/** A third of the row for identifiers, codes, statuses, FK references and audit fields. */
const COMPACT_SPAN = 4
/** Wider for a value that is prose and has to wrap. */
const NARRATIVE_SPAN = 8
/** Narrative names, by the convention the shared spec already uses for talking columns. */
const NARRATIVE_FIELD = /(description|notes|summary|comment|remark|body|message|detail)/i

/** The span a field gets: the caller's hint, else the default for its expected content length. */
function detailSpan(field: DetailField<any>): number {
  if (field.gridSpan) return Math.min(12, Math.max(1, field.gridSpan))
  return NARRATIVE_FIELD.test(field.name) ? NARRATIVE_SPAN : COMPACT_SPAN
}

/** A field's value: the caller's renderer, else the value as text, else `-` when it is absent. */
function DetailValue<Row>({ field, row }: { field: DetailField<Row>; row: Row }) {
  if (field.render) return <>{field.render(row)}</>
  const value = (row as Record<string, unknown>)[field.name]
  return <>{value === null || value === undefined || value === "" ? "-" : String(value)}</>
}

/**
 * The details card for the selected row: the name as a highlighted header, every other declared
 * field in a dense 12-column grid. Rendered by `StandardEntityPage`; not exported, because the
 * spec enumerates the page's parts and this is not one of them (yet).
 */
function DetailsCard<Row extends { id: string | number }>({
  fields,
  row,
}: {
  fields: DetailField<Row>[]
  row: Row
}) {
  const nameField = fields.find((field) => field.isName)
  return (
    <div className="ideable:rounded-md ideable:border ideable:bg-muted">
      {nameField && (
        <div className="ideable:border-b ideable:px-4 ideable:py-2">
          <span className="ideable:text-sm ideable:font-semibold">
            <DetailValue field={nameField} row={row} />
          </span>
        </div>
      )}
      <div className="ideable:grid ideable:grid-cols-12 ideable:gap-2 ideable:p-4">
        {fields
          .filter((field) => field !== nameField)
          .map((field) => {
            const span = detailSpan(field)
            return (
              <div key={field.name} style={{ gridColumn: `span ${span} / span ${span}` }}>
                <div className="ideable:text-xs ideable:text-muted-foreground">{field.label}</div>
                <div className="ideable:text-sm ideable:break-words">
                  <DetailValue field={field} row={row} />
                </div>
              </div>
            )
          })}
      </div>
    </div>
  )
}

/** The selected MAIN row first, then one entry per association level already selected. */
export type AssociationChain = Array<{ level: number; id: string | number; label: string }>

/** The paging/sorting state a level's table produces, plus the level's own `baseParams`. */
export interface AssociationQueryParams extends Record<string, unknown> {
  skip?: number
  after_id?: number
  limit?: number
  sort_by?: string
  sort_order?: "asc" | "desc"
}

/** How one level is fetched and shown, in one visit mode. */
export interface AssociationLevel<Row> {
  columns: ColumnDef<Row, any>[]
  /** One page of this level's rows. `chain[0]` is always the selected main row. */
  query: (params: AssociationQueryParams, chain: AssociationChain) => Promise<PageResult<Row>>
  /** A lightweight count for the tab label (`Permissions (12)`); omit and the label carries none. */
  count?: (chain: AssociationChain) => Promise<number>
  /** Fixed params merged into every request this level makes. */
  baseParams?: (chain: AssociationChain) => Record<string, unknown>
  /**
   * How a row of this level is NAMED in a breadcrumb, e.g. `admin (3)`. A function rather than a
   * field name because the framework's reference format carries the id beside the name. Omit and a
   * selection is named by its id.
   */
  label?: (row: Row) => string
  /**
   * The id THIS row contributes to the chain that a DEEPER level's `baseParams` reads —
   * `chain[index + 1].id`. Omit and the chain carries `row.id`, which is correct whenever this
   * level's rows already ARE the referenced entity.
   *
   * It is NOT correct when this level's rows are a join/grant row reached THROUGH the entity
   * rather than the entity itself — e.g. a Users page's Profiles level reads `as_user_profile`,
   * whose own `id` is a synthetic composite of every key the grant carries
   * (`ideable_api.associations.synthetic_id`, e.g. `user_fk__profile_fk__tenant_fk`), not the
   * profile's id. A deeper level's `baseParams` scoped by `profile_fk: chain[1]?.id` then sent
   * that composite string as the filter value: the backend found no row to match, one hop's
   * selection produced "No results" on the very next tab, and nothing about it looked wrong on a
   * static read of either level's wiring, because each read its OWN chain slot correctly — only
   * the value written INTO that slot was the wrong id.
   */
  chainId?: (row: Row) => string | number
  /**
   * The fields a create form collects for this level — § *Associated entities in tables* makes the
   * Add button normative on an association table, and a level IS one. Omit and no add affordance is
   * offered at all.
   */
  formFields?: EntityFormField[]
  /** Create one row of this level from the form's values. Required for the add affordance. */
  create?: (values: Record<string, unknown>, chain: AssociationChain) => Promise<unknown>
  /** Remove one row's association; omit and no unlink action is offered. */
  unlink?: (row: Row, chain: AssociationChain) => Promise<unknown>
  /**
   * Edit one row of this level — § *Associated entities in tables* requires editable association
   * attributes. Omit and no edit action is offered. Reuses `formFields` as the edit form.
   */
  update?: (row: Row, values: Record<string, unknown>, chain: AssociationChain) => Promise<unknown>
  /** Whether this caller may write THIS level — resolved by the MODULE, like the page's `canEdit`. */
  canWrite?: boolean
  /** Already-translated labels for the affordances: `createLabel` names the ADD button,
   *  `createSubmitLabel` the create form's submit button, `saveLabel` the edit form's submit. */
  createLabel?: string
  createSubmitLabel?: string
  saveLabel?: string
  unlinkLabel?: string
}

/** One association level of the entity, declared for both visit modes. */
export interface AssociationTab<Row> {
  id: string
  /** The tab's breadcrumb label; the function form receives the chain so far. */
  label: string | ((chain: AssociationChain) => string)
  /** Depth visit: this level's rows are the ones associated with the previous level's selection. */
  depth: AssociationLevel<Row>
  /** Full perspective: every row reachable from the selected main row, with its provenance columns. */
  full: AssociationLevel<Row>
}

type VisitMode = "depth" | "full"

/** The level a tab uses in the current mode. */
function levelFor<Row>(tab: AssociationTab<Row>, mode: VisitMode): AssociationLevel<Row> {
  return mode === "depth" ? tab.depth : tab.full
}

/** How a row is named in a breadcrumb: the level's own labeller, else its id. */
function rowName<Row extends { id: string | number }>(
  row: Row,
  label?: (row: Row) => string,
): string {
  return label ? label(row) : String(row.id)
}

/**
 * A tab's counter, fetched whether or not the tab has been opened — § *Tab mounting vs counters*:
 * the counter is eager and the TABLE is lazy, which is what keeps an unopened tab to one request.
 *
 * Its own component because a counter per tab is a query per tab, and a hook cannot live in a loop.
 * Reports upward rather than rendering, so the strip stays one row of buttons.
 *
 * Plain state + effect, NOT react-query: the standard page is consumed by modules that do not mount
 * a `QueryClientProvider` (module_template does not), so the page must not require one — the same
 * reason `useEntityQuery` fetches without react-query.
 */
function AssociationCount<Row>({
  tabId,
  tab,
  mode,
  chain,
  enabled,
  setCounts,
  refreshToken,
}: {
  tabId: string
  tab: AssociationTab<Row>
  mode: VisitMode
  chain: AssociationChain
  enabled: boolean
  setCounts: React.Dispatch<React.SetStateAction<Record<string, number | null>>>
  refreshToken: number
}) {
  const level = levelFor(tab, mode)
  useEffect(() => {
    if (!enabled || !level.count) return
    let cancelled = false
    level
      .count(chain)
      .then((count) => {
        if (cancelled) return
        setCounts((previous) =>
          previous[tabId] === count ? previous : { ...previous, [tabId]: count },
        )
      })
      .catch(() => {
        if (cancelled) return
        setCounts((previous) =>
          previous[tabId] === null ? previous : { ...previous, [tabId]: null },
        )
      })
    return () => {
      cancelled = true
    }
  }, [enabled, level, chain, tabId, setCounts, refreshToken])
  return null
}

/** One level's table. Only the active tab renders one — the others cost their counter and nothing. */
function AssociationTable<Row extends { id: string | number }>({
  level,
  chain,
  enabled,
  selectedRow,
  onRowSelect,
  canWrite,
  unlinkLabel,
  onUnlink,
  onEdit,
  refreshToken,
}: {
  level: AssociationLevel<Row>
  chain: AssociationChain
  enabled: boolean
  selectedRow: Row | null
  onRowSelect: (row: Row | null) => void
  canWrite: boolean
  unlinkLabel?: string
  onUnlink?: (row: Row) => void
  onEdit?: (row: Row) => void
  refreshToken: number
}) {
  const { t } = useTranslation()
  const table = useServerTableState({})
  // Filters travel as bare per-column params, exactly as `useEntityQuery` sends them: the generated
  // entity endpoints read per-column params (the descriptor splices `__filterable__` into the
  // signature), and a caller whose endpoint speaks the hand-written routers' JSON `filters`
  // convention adapts inside its own `query`. Sending a JSON `filters` string here would make every
  // standard association table's filters inert on a generated endpoint — card item 4's defect.
  const params = useMemo<AssociationQueryParams>(
    () => ({
      ...table.queryParams,
      ...(level.baseParams ? level.baseParams(chain) : {}),
      ...table.debouncedFilters,
    }),
    [table.queryParams, table.debouncedFilters, level, chain],
  )

  // Plain state + effect, NOT react-query (see `AssociationCount`): the standard page must not
  // require a `QueryClientProvider`, which `host_app` mounts and `module_template` does not.
  const [rows, setRows] = useState<Row[]>([])
  const [total, setTotal] = useState(0)
  const [fetchError, setFetchError] = useState<Error | null>(null)
  const [fetching, setFetching] = useState(false)

  useEffect(() => {
    if (!enabled) return
    let cancelled = false
    setFetching(true)
    level
      .query(params, chain)
      .then((page) => {
        if (cancelled) return
        setRows(page.items ?? [])
        setTotal(page.total ?? 0)
        setFetchError(null)
      })
      .catch((cause) => {
        // Rows cleared on failure, not left: a stale page under a new filter answers a different
        // question than the one asked — the same rule `useEntityQuery` states.
        if (cancelled) return
        setRows([])
        setTotal(0)
        setFetchError(cause instanceof Error ? cause : new Error(String(cause)))
      })
      .finally(() => {
        if (!cancelled) setFetching(false)
      })
    return () => {
      cancelled = true
    }
  }, [enabled, level, params, chain, refreshToken])

  const columns = useMemo<ColumnDef<Row, any>[]>(() => {
    if (!canWrite || (!level.update && !level.unlink)) return level.columns
    return [
      ...level.columns,
      {
        id: "actions",
        header: "",
        enableSorting: false,
        enableColumnFilter: false,
        cell: ({ row }: { row: { original: Row } }) => (
          <RowActions>
            {level.update && onEdit && (
              <RowActionButton
                icon={PencilIcon}
                aria-label={t("standardPage.edit")}
                onClick={() => onEdit(row.original)}
              />
            )}
            {level.unlink && onUnlink && (
              <RowActionButton
                icon={TrashIcon}
                variant="danger"
                aria-label={unlinkLabel ?? t("standardPage.unlink")}
                onClick={() => onUnlink(row.original)}
              />
            )}
          </RowActions>
        ),
      } as ColumnDef<Row, any>,
    ]
  }, [canWrite, level.columns, level.update, level.unlink, onEdit, onUnlink, unlinkLabel])

  return (
    <div className="ideable:relative ideable:space-y-2">
      {fetchError && (
        <div className="ideable:text-sm ideable:text-destructive">
          {fetchError.message || t("table.errorLoading")}
        </div>
      )}
      {fetching && (
        <div className="ideable:absolute ideable:inset-0 ideable:z-10 ideable:flex ideable:items-center ideable:justify-center ideable:bg-background/50 ideable:pointer-events-none">
          <span className="ideable:text-sm ideable:text-muted-foreground">{t("table.updating")}</span>
        </div>
      )}
      <ServerDataTable<Row>
        columns={columns}
        data={rows}
        total={total}
        page={table.page}
        pageSize={table.pageSize}
        onPageChange={table.setPage}
        onPageSizeChange={table.setPageSize}
        onSortChange={table.onSortChange}
        onFilterChange={table.onFilterChange}
        filters={table.filters}
        onRowSelect={onRowSelect}
        selectedRow={selectedRow}
      />
    </div>
  )
}

/**
 * The association view: the visit-mode toggle, the breadcrumb tabs strip, and the ONE association
 * table the active tab selects. `StandardEntityPage` renders it; not exported, because the spec
 * enumerates the page's parts and this is not one of them (yet).
 *
 * The page owns the mechanics — the toggle, the labels, one table at a time, the eager counters and
 * the pruning — and the caller owns the levels: what each one is called, how it is fetched, and how
 * its rows are named. The page cannot know a module's datamodel, which is why every one of those is
 * a parameter rather than something derived here.
 */
function AssociationView<Row extends { id: string | number }>({
  associations,
  mode,
  onModeChange,
  selected,
  rowLabel,
  editMode,
}: {
  associations: AssociationTab<Row>[]
  mode: VisitMode
  onModeChange: (mode: VisitMode) => void
  selected: Row | null
  rowLabel?: (row: Row) => string
  editMode: boolean
}) {
  const { t } = useTranslation()
  const [activeId, setActiveId] = useState<string>(associations[0]?.id ?? "")
  const [chain, setChain] = useState<AssociationChain>([])
  const [counts, setCounts] = useState<Record<string, number | null>>({})
  const [picked, setPicked] = useState<Record<string, any | null>>({})
  const [adding, setAdding] = useState(false)
  const [editing, setEditing] = useState<any | null>(null)
  // Same rationale as the main entity's `formError` above: `EntityForm` calls `onSubmit` as
  // `void onSubmit(values)`, so a rejected `create`/`update` promise here was an unhandled
  // rejection with nothing visible in the dialog to explain it.
  const [formError, setFormError] = useState<string | null>(null)
  // Bumped after a create/unlink/update, so the active table and the counters refetch. State rather
  // than a react-query cache key, because the page must not require a QueryClientProvider.
  const [refreshToken, setRefreshToken] = useState(0)

  // A new selection, or a different mode, starts the walk over: `chain[0]` IS the main row, and
  // nothing selected under a different one survives it.
  useEffect(() => {
    setChain(selected ? [{ level: 0, id: selected.id, label: rowName(selected, rowLabel) }] : [])
    setActiveId(associations[0]?.id ?? "")
    setPicked({})
  }, [selected, mode, associations, rowLabel])

  const enabledAt = (index: number) => mode === "full" || chain.length >= index + 1
  const activeIndex = Math.max(0, associations.findIndex((tab) => tab.id === activeId))
  const activeTab = associations[activeIndex]
  const activeLevel = activeTab ? levelFor(activeTab, mode) : null
  // The two-part gate the spec states: the host shell is in edit mode AND this level's caller may
  // write. `canWrite` is the module's answer, resolved where host_app's permissions live.
  const mayWrite = editMode && Boolean(activeLevel?.canWrite)

  // A tab whose upstream selection is gone cannot stay open: fall back to the nearest that can be.
  useEffect(() => {
    const firstDisabled = associations.findIndex((_, index) => !enabledAt(index))
    if (firstDisabled !== -1 && activeIndex >= firstDisabled) {
      setActiveId(associations[Math.max(0, firstDisabled - 1)].id)
    }
  }, [associations, activeIndex, chain, mode])

  const select = (index: number, row: any | null) => {
    const tab = associations[index]
    const level = levelFor(tab, mode)
    setPicked((previous) => ({ ...previous, [tab.id]: row }))
    if (!row) {
      // Deselecting prunes everything downstream: the rows below were THIS row's rows.
      setChain((previous) => previous.slice(0, index + 1))
      return
    }
    // `chainId`, when the level declares one — else `row.id`, which is only the referenced
    // entity's own id when this level's rows ARE that entity rather than a join/grant row
    // reached through it (see `AssociationLevel.chainId`).
    const chainedId = level.chainId ? level.chainId(row) : row.id
    setChain((previous) => [
      ...previous.slice(0, index + 1),
      { level: index + 1, id: chainedId, label: rowName(row, level.label) },
    ])
    const next = associations[index + 1]
    if (next) setActiveId(next.id)
  }

  const labelOf = (tab: AssociationTab<Row>) => {
    const text = typeof tab.label === "function" ? tab.label(chain) : tab.label
    const count = counts[tab.id]
    return count === null || count === undefined ? text : `${text} (${count})`
  }

  return (
    <div className="ideable:space-y-4">
      <div
        className="ideable:flex ideable:items-center ideable:gap-2"
        role="group"
        aria-label={t("standardPage.visitMode")}
      >
        <Button
          variant={mode === "depth" ? "default" : "outline"}
          size="sm"
          onClick={() => onModeChange("depth")}
        >
          {t("standardPage.depthVisit")}
        </Button>
        <Button
          variant={mode === "full" ? "default" : "outline"}
          size="sm"
          onClick={() => onModeChange("full")}
        >
          {t("standardPage.fullPerspective")}
        </Button>
      </div>

      <div
        className="ideable:flex ideable:items-center ideable:gap-2 ideable:border-b"
        role="tablist"
        aria-label={t("standardPage.visitMode")}
      >
        {associations.map((tab, index) => (
          <Button
            key={tab.id}
            role="tab"
            aria-selected={tab.id === activeId}
            variant={tab.id === activeId ? "default" : "ghost"}
            size="sm"
            disabled={!enabledAt(index)}
            onClick={() => setActiveId(tab.id)}
          >
            {labelOf(tab)}
          </Button>
        ))}
      </div>

      {associations.map((tab, index) => (
        <AssociationCount<any>
          key={`count-${tab.id}`}
          tabId={tab.id}
          tab={tab}
          mode={mode}
          chain={chain}
          enabled={Boolean(selected) && enabledAt(index)}
          setCounts={setCounts}
          refreshToken={refreshToken}
        />
      ))}

      {selected && activeTab && activeLevel && enabledAt(activeIndex) ? (
        <div className="ideable:space-y-4">
          {mayWrite && activeLevel.formFields?.length && activeLevel.create && (
            <div className="ideable:flex ideable:items-center ideable:gap-2">
              <Button
                onClick={() => {
                  setFormError(null)
                  setAdding((open) => !open)
                }}
              >
                {adding ? t("common.cancel") : (activeLevel.createLabel ?? t("standardPage.add"))}
              </Button>
            </div>
          )}
          {formError && (adding || editing) && (
            <p role="alert" className="ideable:text-sm ideable:text-red-600">{formError}</p>
          )}
          {adding && mayWrite && activeLevel.formFields && activeLevel.create && (
            <EntityForm
              fields={activeLevel.formFields}
              submitLabel={activeLevel.createSubmitLabel ?? t("standardPage.add")}
              cancelLabel={t("common.cancel")}
              onCancel={() => {
                setFormError(null)
                setAdding(false)
              }}
              onSubmit={async (values) => {
                try {
                  await activeLevel.create!(values, chain)
                } catch (error) {
                  setFormError(error instanceof Error ? error.message : String(error))
                  return
                }
                setFormError(null)
                setAdding(false)
                setRefreshToken((n) => n + 1)
              }}
            />
          )}
          {editing && mayWrite && activeLevel.formFields && activeLevel.update && (
            <EntityForm
              fields={activeLevel.formFields}
              value={editing}
              submitLabel={activeLevel.saveLabel ?? t("common.save")}
              cancelLabel={t("common.cancel")}
              onCancel={() => {
                setFormError(null)
                setEditing(null)
              }}
              onSubmit={async (values) => {
                try {
                  await activeLevel.update!(editing, values, chain)
                } catch (error) {
                  setFormError(error instanceof Error ? error.message : String(error))
                  return
                }
                setFormError(null)
                setEditing(null)
                setRefreshToken((n) => n + 1)
              }}
            />
          )}
          <AssociationTable<any>
            level={activeLevel}
            chain={chain}
            enabled
            selectedRow={picked[activeTab.id] ?? null}
            onRowSelect={(row) => select(activeIndex, row)}
            canWrite={mayWrite}
            unlinkLabel={activeLevel.unlinkLabel}
            onEdit={
              activeLevel.update
                ? (row) => {
                    setFormError(null)
                    setEditing(row)
                  }
                : undefined
            }
            refreshToken={refreshToken}
            onUnlink={
              activeLevel.unlink
                ? async (row) => {
                    await activeLevel.unlink!(row, chain)
                    setRefreshToken((n) => n + 1)
                  }
                : undefined
            }
          />
        </div>
      ) : (
        <p className="ideable:text-sm ideable:text-muted-foreground">
          {t("standardPage.selectRowForAssociations")}
        </p>
      )}
    </div>
  )
}

export interface StandardEntityPageProps<Row extends { id: string | number }> {
  /** The entity key as declared in the module's registry. */
  entityKey: string
  /** How to reach this module's API. */
  transport: EntityTransport
  /** The page heading. Already translated — the widget resolves its own chrome, not your copy. */
  title: string
  /** Columns to draw; omit to render one per field the descriptor reports. */
  columns?: ColumnDef<Row, any>[]
  labelFor?: (field: string) => string
  /** Rendered above the table — a create button, a filter chip row, anything the page needs. */
  toolbar?: React.ReactNode
  /**
   * The selected row's details card: every attribute of the entity, including those the table does
   * not show. Omit and no card is rendered — the layout's item 2 is the CALLER's to supply, and a
   * card the page invented from the descriptor would show the read schema's declaration order
   * rather than what a reader needs.
   */
  detailFields?: DetailField<Row>[]
  /**
   * The entity's association levels, in depth order — the visit-mode toggle, the breadcrumb strip
   * and the one association table the active tab selects. Omit and the page renders none of them:
   * items 3–5 of the layout presuppose an entity with associations, and a toggle with nothing to
   * switch between offers the user a choice that does nothing.
   */
  // `any`, not `Row`: each level is a DIFFERENT entity than the main one (`items`'s sub-items are
  // not `items`), so one page-level generic cannot name the rows of a heterogeneous level list.
  associations?: AssociationTab<any>[]
  /** How the selected MAIN row is named in a breadcrumb. Omit and it is named by its id. */
  rowLabel?: (row: Row) => string
  /** Control the toggle; leave both out and the page owns it, starting on `Depth visit`. */
  visitMode?: "depth" | "full"
  onVisitModeChange?: (mode: "depth" | "full") => void
  /**
   * Rendered under the table, with the currently selected row. This is where an ASSOCIATED entity
   * belongs: a second `EntityTable` filtered by the selection, which is what a master/detail page
   * is. Given the row rather than an id so a caller can label the section with its own fields.
   */
  detail?: (row: Row | null) => React.ReactNode
  /** Fixed query params merged into every request this page makes — see `EntityTable`'s
   *  `baseParams`. For THIS page composed as someone else's `detail(row)`, e.g. `{ item_fk:
   *  parent.id }`, so a nested `StandardEntityPage` is a detail region rather than a new
   *  mechanism. */
  baseParams?: Record<string, unknown>
  isEditMode?: boolean
  onBulkDelete?: (rows: Row[]) => void
  /** Audit-trail column ids, in order. Omit to hide the trail even for a versioned entity. */
  auditColumns?: string[]
  /**
   * Fetch one page of history. Omit to hide the trail.
   *
   * Typed with the popup's OWN parameter and page types rather than a loose record: the audit
   * trail is a framework contract with a fixed shape, and widening it here would let a caller
   * return something the popup cannot render, discovered at runtime.
   */
  fetchHistoryPage?: (rowId: string | number, params: AuditPageParams) => Promise<VersionPage>
  historyLabel?: string
  defaultPageSize?: number
  /**
   * Render a refusal or a failure instead of the table.
   *
   * A permission the caller does not hold is not a transient error and must not be drawn as an
   * empty table: an empty table says "there is nothing here", which is a different and misleading
   * claim. The message is the module's, because it needs translating — the page only decides WHEN
   * to show one, which is as soon as the entity could not be read at all.
   */
  renderError?: (error: Error) => React.ReactNode
  /**
   * The fields a create form collects. Omit and no create affordance is offered at all.
   *
   * Required rather than inferred from the descriptor, by the same decision as `EntityForm`:
   * inference gets a date, a foreign key or an enum wrong, and the page cannot then correct it.
   */
  formFields?: EntityFormField[]
  /**
   * Whether this caller may write. Resolved by the MODULE, because host_app resolves permissions
   * from its authorization tables and the access token deliberately carries none — a widget that
   * decided this for itself would be reading a token that cannot answer.
   */
  canEdit?: boolean
  createLabel?: string
  editLabel?: string
  deleteLabel?: string
  saveLabel?: string
  deleteConfirmMessage?: string
  createSubmitLabel?: string
  cancelLabel?: string
}

export function StandardEntityPage<Row extends { id: string | number }>({
  entityKey,
  transport,
  title,
  columns,
  labelFor,
  toolbar,
  detailFields,
  associations,
  rowLabel,
  visitMode,
  onVisitModeChange,
  detail,
  isEditMode,
  onBulkDelete,
  auditColumns,
  fetchHistoryPage,
  historyLabel,
  defaultPageSize,
  renderError,
  formFields,
  baseParams,
  canEdit = false,
  createLabel,
  editLabel,
  deleteLabel,
  saveLabel,
  deleteConfirmMessage,
  createSubmitLabel,
  cancelLabel,
}: StandardEntityPageProps<Row>) {
  // Asks for the descriptor only — one request, no rows — so a refusal is known before the table
  // mounts and cannot be mistaken for "no data".
  const probe = useEntityQuery<Row>(entityKey, transport, { enabled: Boolean(renderError), baseParams })
  const [selected, setSelected] = useState<Row | null>(null)
  const [auditRowId, setAuditRowId] = useState<string | number | null>(null)
  // Held in a ref, not state: a parent calling `refresh()` after a write must not re-render this
  // component merely because the query object identity changed.
  const query = useRef<UseEntityQueryResult<Row> | null>(null)
  const onReady = useCallback((result: UseEntityQueryResult<Row>) => {
    query.current = result
  }, [])

  const [creating, setCreating] = useState(false)
  const [editing, setEditing] = useState<Row | null>(null)
  // A create/edit `onSubmit` is called as `void onSubmit(values)` by `EntityForm` (it cannot know
  // whether a caller's submit returns a promise worth awaiting the rejection of), so a transport
  // failure here was an UNHANDLED REJECTION: the dialog stayed open with no visible reason, DevTools
  // showed nothing a page reader would think to open, and the network log was the only place the
  // failure existed at all. Surfaced here instead, next to whichever form raised it.
  const [formError, setFormError] = useState<string | null>(null)
  // Uncontrolled unless the caller controls it, and `Depth visit` is the default the spec states.
  const [ownVisitMode, setOwnVisitMode] = useState<VisitMode>("depth")
  const mode: VisitMode = visitMode ?? ownVisitMode
  const editMode = useHostEditMode()
  // BOTH, and the two say different things: edit mode is what the user asked the shell for, the
  // permission is what host_app says they may do. Offering Create on either alone would either
  // clutter a reading session or invite a 403.
  const mayCreate = editMode && canEdit && Boolean(formFields?.length) && Boolean(transport.post)

  const mayWrite = editMode && canEdit && Boolean(formFields?.length)
  const showTrail = Boolean(fetchHistoryPage && auditColumns?.length)

  // The actions column, appended to whatever columns the caller chose.
  //
  // ORDER IS PART OF THE CONTRACT, not a layout choice: history, edit, delete. They are icon-only
  // buttons, so position is the only thing identifying them to a test — and to a user who has
  // learned where the destructive one sits. Delete stays last for the same reason.
  const columnsWithActions = useMemo<ColumnDef<Row, any>[] | undefined>(() => {
    if (!columns) return columns
    if (!showTrail && !mayWrite) return columns
    return [
      ...columns,
      {
        id: "actions",
        header: "",
        enableSorting: false,
        enableColumnFilter: false,
        cell: ({ row }: { row: { original: Row } }) => (
          <RowActions>
            {showTrail && (
              <RowActionButton
                icon={HistoryIcon}
                aria-label={historyLabel ?? "History"}
                onClick={() => setAuditRowId(row.original.id)}
              />
            )}
            {mayWrite && (
              <RowActionButton
                icon={PencilIcon}
                aria-label={editLabel ?? "Edit"}
                onClick={() => {
                  setFormError(null)
                  setEditing(row.original)
                }}
              />
            )}
            {mayWrite && Boolean(transport.delete) && (
              <RowActionButton
                icon={TrashIcon}
                variant="danger"
                aria-label={deleteLabel ?? "Delete"}
                onClick={async () => {
                  // A native confirm, deliberately: deleting a row is irreversible and the shell
                  // has no dialog contract for it. A page that wants its own passes `onBulkDelete`
                  // or writes its own actions column.
                  if (!window.confirm(deleteConfirmMessage ?? "Delete this row?")) return
                  await transport.delete!(`/${entityKey}/${row.original.id}`)
                  query.current?.refresh()
                }}
              />
            )}
          </RowActions>
        ),
      } as ColumnDef<Row, any>,
    ]
  }, [columns, showTrail, mayWrite, transport, entityKey, historyLabel, editLabel, deleteLabel,
      deleteConfirmMessage])

  // The descriptor read is the page's own authorization probe: it carries the same permission the
  // list does, so a caller who may not see the entity fails here, before any row is requested.
  const failure = probe.error

  return (
    <div className="ideable:flex ideable:flex-col ideable:gap-4">
      {/*
        * The refusal is shown WITH the grid, not instead of it, and that is the contract rather
        * than a layout preference: a message over POPULATED rows would mean the data had already
        * been fetched and the guard was decoration. Shown above an EMPTY grid, the two together
        * say what actually happened — the rows were never returned.
        *
        * It also means this component has no early return, so no later edit can make a hook
        * conditional by adding one above it.
        */}
      {failure && renderError && <>{renderError(failure)}</>}

      {(toolbar || mayCreate) && (
        <div className="ideable:flex ideable:items-center ideable:gap-2">
          {toolbar}
          {mayCreate && (
            <Button
              onClick={() => {
                setFormError(null)
                setCreating((open) => !open)
              }}
            >
              {creating ? (cancelLabel ?? "Cancel") : (createLabel ?? "Create")}
            </Button>
          )}
        </div>
      )}

      {creating && formFields && (
        <>
          {formError && <p role="alert" className="ideable:text-sm ideable:text-red-600">{formError}</p>}
          <EntityForm
            fields={formFields}
            submitLabel={createSubmitLabel ?? "Create"}
            cancelLabel={cancelLabel}
            onCancel={() => {
              setFormError(null)
              setCreating(false)
            }}
            onSubmit={async (values) => {
              try {
                await transport.post!(`/${entityKey}`, values)
              } catch (error) {
                setFormError(error instanceof Error ? error.message : String(error))
                return
              }
              setFormError(null)
              setCreating(false)
              // The table refetches rather than inserting the row it just sent: the server assigns
              // the id and may derive fields, so appending the payload would show something that is
              // not what was stored.
              query.current?.refresh()
            }}
          />
        </>
      )}

      <EntityTable<Row>
        entityKey={entityKey}
        transport={transport}
        columns={columnsWithActions}
        labelFor={labelFor}
        title={title}
        isEditMode={isEditMode}
        onRowSelect={setSelected}
        selectedRow={selected}
        onBulkDelete={onBulkDelete}
        onReady={onReady}
        defaultPageSize={defaultPageSize}
        baseParams={baseParams}
      />

      {editing && formFields && (
        <>
          {formError && <p role="alert" className="ideable:text-sm ideable:text-red-600">{formError}</p>}
          <EntityForm
            fields={formFields}
            value={editing as unknown as Record<string, unknown>}
            submitLabel={saveLabel ?? "Save"}
            cancelLabel={cancelLabel}
            onCancel={() => {
              setFormError(null)
              setEditing(null)
            }}
            onSubmit={async (values) => {
              try {
                await transport.put!(`/${entityKey}/${(editing as { id: string | number }).id}`, values)
              } catch (error) {
                setFormError(error instanceof Error ? error.message : String(error))
                return
              }
              setFormError(null)
              setEditing(null)
              query.current?.refresh()
            }}
          />
        </>
      )}

      {selected && detailFields?.length ? (
        <div data-detail-region>
          <DetailsCard fields={detailFields} row={selected} />
        </div>
      ) : null}

      {associations?.length ? (
        <div data-detail-region>
          <AssociationView<Row>
            associations={associations}
            mode={mode}
            onModeChange={(next) => {
              setOwnVisitMode(next)
              onVisitModeChange?.(next)
            }}
            selected={selected}
            rowLabel={rowLabel}
            editMode={editMode}
          />
        </div>
      ) : null}

      {detail && <div data-detail-region>{detail(selected)}</div>}

      {showTrail && auditRowId !== null && (
        <AuditTrailPopup
          open
          onClose={() => setAuditRowId(null)}
          entityLabel={title}
          tabs={[
            {
              label: historyLabel ?? title,
              columns: auditColumns as string[],
              fetchPage: (params: AuditPageParams) => fetchHistoryPage!(auditRowId, params),
            },
          ]}
        />
      )}
    </div>
  )
}
