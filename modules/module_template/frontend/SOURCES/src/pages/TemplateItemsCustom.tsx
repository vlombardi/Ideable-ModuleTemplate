/**
 * A CUSTOM page for the same entity — the escape hatch, worked.
 *
 * Nothing here is standard except the parts it reuses. The page owns its layout, adds content the
 * standard page has no notion of, and still gets the entity's table from `@ideable/ui` rather than
 * copying one. That is the property that makes replacing a page cheap: a module changes what it
 * renders, not how an entity is fetched, paged, filtered or authorised.
 *
 * It exists as a PROOF, and it is not mounted on a menu item by default — the template ships the
 * standard page (`TemplateItems.tsx`) as its worked example. Repointing `moduleManifest.ts` at this
 * component, and back, is the substitution both directions of which must cost nothing: the
 * generated endpoints stay mounted either way, so neither choice takes anything away.
 */
import { useMemo, useState } from 'react'
import { EntityTable, useEntityQuery } from '@ideable/ui'
import { useTranslation } from '../hooks/useTranslation'
import { entityTransport } from '../services/entityTransport'
import { type TemplateItem } from '../services/templateItems'
import '../index.css'

export default function TemplateItemsCustom() {
  const { t } = useTranslation()
  const [selected, setSelected] = useState<TemplateItem | null>(null)

  // The same hook the standard page uses, called directly — a custom page reads the descriptor and
  // the rows on its own terms, without a second fetching layer written for this module.
  const { descriptor, total, loading } = useEntityQuery<TemplateItem>('items', entityTransport)

  const labelFor = useMemo(() => {
    const labels: Record<string, string> = {
      id: t('templateItems.columns.id'),
      name: t('templateItems.columns.name'),
      description: t('templateItems.columns.description'),
    }
    return (field: string) => labels[field] ?? field
  }, [t])

  return (
    <div className="ideable-scope ideable:flex ideable:flex-col ideable:gap-4">
      {/* Content the standard page has no notion of — the reason this page exists at all. */}
      <section className="ideable:rounded-md ideable:border ideable:p-4">
        <h2 className="ideable:text-lg ideable:font-semibold">{t('templateItems.title')}</h2>
        <p className="ideable:text-sm ideable:text-muted-foreground">
          {loading ? '…' : `${total}`} · {descriptor?.filterable.join(', ') ?? ''}
        </p>
      </section>

      <EntityTable<TemplateItem>
        entityKey="items"
        transport={entityTransport}
        labelFor={labelFor}
        title={t('templateItems.title')}
        onRowSelect={setSelected}
        selectedRow={selected}
      />

      {selected && (
        <section className="ideable:rounded-md ideable:border ideable:p-4">
          <h3 className="ideable:text-base ideable:font-semibold">{selected.name}</h3>
          <p className="ideable:text-sm">{selected.description ?? ''}</p>
        </section>
      )}
    </div>
  )
}
