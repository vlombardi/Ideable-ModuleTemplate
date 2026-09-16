import { useState } from 'react'
import {
  TimeSeriesChart,
  type TimeSeriesPoint,
  ServerDataTable,
  type ColumnDef,
  DraggableResizablePopup,
  AuditTrailPopup,
  type AuditPageParams,
  type VersionPage,
  UnsavedChangesDialog,
  DynamicIcon,
  Button,
  Input,
  Label,
  Checkbox,
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
  Tabs,
  TabsList,
  TabsTrigger,
  TabsContent,
  Tooltip,
  TooltipTrigger,
  TooltipContent,
  TooltipProvider,
  Select,
  SelectTrigger,
  SelectValue,
  SelectContent,
  SelectItem,
} from '@ideable/ui'
import '../index.css'

/**
 * WidgetGallery — dev-only reference page demonstrating the @ideable/ui framework
 * widgets, logically connected to the Items entity (sample Items-shaped data).
 *
 * This is the live example the `ideable-ui` skill points at. It is excluded from
 * published module images via the WIDGET_EXAMPLES build arg (see Dockerfile /
 * build_and_deploy.py / push_module_images_to_registry.py).
 */

interface DemoItem {
  id: number
  name: string
  description: string
  active: boolean
}

const DEMO_ITEMS: DemoItem[] = [
  { id: 1, name: 'Widget Alpha', description: 'First sample item', active: true },
  { id: 2, name: 'Widget Beta', description: 'Second sample item', active: false },
  { id: 3, name: 'Widget Gamma', description: 'Third sample item', active: true },
  { id: 4, name: 'Widget Delta', description: 'Fourth sample item', active: true },
  { id: 5, name: 'Widget Epsilon', description: 'Fifth sample item', active: false },
]

const DEMO_ITEMS_OVER_TIME: TimeSeriesPoint[] = [
  { x: '2026-01', created: 4, updated: 1 },
  { x: '2026-02', created: 7, updated: 3 },
  { x: '2026-03', created: 5, updated: 6 },
  { x: '2026-04', created: 9, updated: 4 },
  { x: '2026-05', created: 12, updated: 8 },
  { x: '2026-06', created: 8, updated: 5 },
]

// Synthetic audit history for the AuditTrailPopup demo.
function demoFetchHistory(_params: AuditPageParams): Promise<VersionPage> {
  const items = [
    { transaction_id: 3, operation_type: 1, timestamp: '2026-06-03T10:00:00Z', actor: 'alice', actor_id: 1, name: 'Widget Alpha' },
    { transaction_id: 2, operation_type: 1, timestamp: '2026-05-20T09:30:00Z', actor: 'bob', actor_id: 2, name: 'Alpha' },
    { transaction_id: 1, operation_type: 0, timestamp: '2026-05-01T08:00:00Z', actor: 'alice', actor_id: 1, name: 'Alpha' },
  ]
  return Promise.resolve({ items, total: items.length, page: 1, size: 20, pages: 1 })
}

function Section({ title, description, children }: { title: string; description?: string; children: React.ReactNode }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        {description && <CardDescription>{description}</CardDescription>}
      </CardHeader>
      <CardContent className="template:space-y-4">{children}</CardContent>
    </Card>
  )
}

export default function WidgetGallery() {
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(10)
  const [selectedRow, setSelectedRow] = useState<DemoItem | null>(null)
  const [popupOpen, setPopupOpen] = useState(false)
  const [auditOpen, setAuditOpen] = useState(false)
  const [unsavedOpen, setUnsavedOpen] = useState(false)
  const [checked, setChecked] = useState(true)
  const [selectValue, setSelectValue] = useState('option-1')

  const columns: ColumnDef<DemoItem>[] = [
    { id: 'id', accessorKey: 'id', header: 'ID', meta: { sortable: true } },
    { id: 'name', accessorKey: 'name', header: 'Name', meta: { sortable: true } },
    { id: 'description', accessorKey: 'description', header: 'Description', meta: { sortable: true } },
    {
      id: 'active',
      accessorKey: 'active',
      header: 'Active',
      meta: { type: 'boolean' },
      cell: ({ row }) => (row.original.active ? 'Yes' : 'No'),
    },
  ]

  return (
    <TooltipProvider>
      <div className="template-scope ideable-scope template:space-y-6" data-lf="hostapp">
        <div className="template:space-y-1">
          <h1 className="template:text-3xl template:font-bold">Ideable UI — Widget Examples</h1>
          <p className="template:text-sm template:text-muted-foreground">
            Live reference implementations of the <code>@ideable/ui</code> framework widgets,
            connected to the Items entity. Development-only; excluded from published module images.
          </p>
        </div>

        <Section title="Buttons" description="Button variants and sizes (@ideable/ui/primitives/button).">
          <div className="template:flex template:flex-wrap template:gap-2">
            <Button>Default</Button>
            <Button variant="secondary">Secondary</Button>
            <Button variant="destructive">Destructive</Button>
            <Button variant="outline">Outline</Button>
            <Button variant="ghost">Ghost</Button>
            <Button variant="link">Link</Button>
            <Button size="sm">Small</Button>
            <Button size="lg">Large</Button>
          </div>
        </Section>

        <Section title="Form inputs" description="Input, Label, Checkbox, Select.">
          <div className="template:grid template:gap-4 template:md:grid-cols-2">
            <div className="template:space-y-1">
              <Label htmlFor="demo-name">Item name</Label>
              <Input id="demo-name" placeholder="Enter item name" />
            </div>
            <div className="template:space-y-1">
              <Label htmlFor="demo-status">Status</Label>
              <Select value={selectValue} onValueChange={setSelectValue}>
                <SelectTrigger id="demo-status" aria-label="Status"><SelectValue placeholder="Select status" /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="option-1">Active</SelectItem>
                  <SelectItem value="option-2">Inactive</SelectItem>
                  <SelectItem value="option-3">Archived</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="template:flex template:items-center template:gap-2">
              <Checkbox id="demo-check" checked={checked} onCheckedChange={(v) => setChecked(!!v)} />
              <Label htmlFor="demo-check">Item is active</Label>
            </div>
          </div>
        </Section>

        <Section title="Tabs & Tooltip" description="Tabs container and hover Tooltip.">
          <Tabs defaultValue="details">
            <TabsList>
              <TabsTrigger value="details">Details</TabsTrigger>
              <TabsTrigger value="history">History</TabsTrigger>
            </TabsList>
            <TabsContent value="details">
              <p className="template:text-sm template:text-muted-foreground">Item detail panel content.</p>
            </TabsContent>
            <TabsContent value="history">
              <p className="template:text-sm template:text-muted-foreground">Item history panel content.</p>
            </TabsContent>
          </Tabs>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button variant="outline">Hover me</Button>
            </TooltipTrigger>
            <TooltipContent>Tooltips use the framework popover tokens.</TooltipContent>
          </Tooltip>
        </Section>

        <Section title="DynamicIcon" description="Renders any lucide icon by name (data-driven menus).">
          <div className="template:flex template:items-center template:gap-3">
            {['Package', 'List', 'Settings', 'History', 'Users'].map((n) => (
              <span key={n} className="template:flex template:items-center template:gap-1 template:text-sm">
                <DynamicIcon name={n} className="template:h-4 template:w-4" /> {n}
              </span>
            ))}
          </div>
        </Section>

        <Section title="ServerDataTable" description="Server-side pagination/sort/filter table (react-table), bound to Items-shaped data.">
          <ServerDataTable<DemoItem>
            columns={columns}
            data={DEMO_ITEMS}
            total={DEMO_ITEMS.length}
            page={page}
            pageSize={pageSize}
            onPageChange={setPage}
            onPageSizeChange={(s) => { setPageSize(s); setPage(1) }}
            selectedRow={selectedRow}
            onRowSelect={setSelectedRow}
          />
        </Section>

        <Section title="Popups & dialogs" description="DraggableResizablePopup, AuditTrailPopup, UnsavedChangesDialog.">
          <div className="template:flex template:flex-wrap template:gap-2">
            <Button variant="outline" onClick={() => setPopupOpen(true)}>Open draggable popup</Button>
            <Button variant="outline" onClick={() => setAuditOpen(true)}>Open audit trail</Button>
            <Button variant="outline" onClick={() => setUnsavedOpen(true)}>Open unsaved-changes dialog</Button>
          </div>
        </Section>

        <Section title="TimeSeriesChart" description="Framework chart (Recharts, token-driven colors, automatic dark mode).">
          <TimeSeriesChart
            data={DEMO_ITEMS_OVER_TIME}
            variant="area"
            series={[
              { key: 'created', label: 'Created' },
              { key: 'updated', label: 'Updated' },
            ]}
          />
        </Section>

        {popupOpen && (
          <DraggableResizablePopup title="Example popup" onClose={() => setPopupOpen(false)}>
            <p className="template:text-sm">Drag by the header, resize from the bottom-right corner.</p>
          </DraggableResizablePopup>
        )}

        {auditOpen && (
          <AuditTrailPopup
            open={auditOpen}
            onClose={() => setAuditOpen(false)}
            entityLabel="Item"
            tabs={[{ label: 'Item History', columns: ['id', 'name', 'timestamp', 'actor'], fetchPage: demoFetchHistory }]}
          />
        )}

        <UnsavedChangesDialog
          open={unsavedOpen}
          title="Unsaved changes"
          description="You have unsaved changes. Save them before leaving, discard them, or keep editing."
          keepEditingLabel="Keep editing"
          discardLabel="Discard"
          saveLabel="Save"
          onKeepEditing={() => setUnsavedOpen(false)}
          onDiscard={() => setUnsavedOpen(false)}
          onSave={() => setUnsavedOpen(false)}
        />
      </div>
    </TooltipProvider>
  )
}
