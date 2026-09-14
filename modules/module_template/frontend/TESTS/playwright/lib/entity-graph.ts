// Entity dependency-tree helper for FK-aware CRUD E2E tests. Parses a module's schema into a
// foreign-key dependency graph and a topological (leaf-first) order, so generated CRUD specs can
// CREATE parents before children (valorizing FK fields) and DELETE in reverse. Force-synced with
// the harness; see rules/testing-guidelines.md § "CRUD E2E tests — Foreign-key ordering".
//
// The input is `database/SPECS/schema.sql` — the generated rendering of the module's models. It
// used to be `datamodel.sql`, which the schema workflow retired; the pointer was stale AND the
// parser could not have read the replacement anyway, because a pg_dump-style schema differs from a
// hand-written one in two ways that both defeated it:
//
//   1. table names are schema-qualified — `CREATE TABLE public.assets (` — and `\w+` stops at the dot;
//   2. foreign keys are NOT inline in the table body. They arrive afterwards as separate
//      statements: `ALTER TABLE ONLY public.assets ADD CONSTRAINT … FOREIGN KEY (company_fk)
//      REFERENCES public.companies(id)`.
//
// So a module with real FKs produced an empty graph, silently, and the "mandatory" FK ordering
// ordered nothing. Both forms are handled now, and the hand-written form still works.

export interface EntityGraph {
  /** All entity table names found in the datamodel. */
  entities: string[]
  /** entity -> list of in-scope parent entities it FK-references. */
  parents: Record<string, string[]>
  /** Topological order, LEAVES FIRST (create in this order; delete in reverse). */
  createOrder: string[]
  /** Entities left unordered because they sit on an FK cycle. */
  cycles: string[]
}

/**
 * Parse a PostgreSQL schema into an FK dependency graph.
 *
 * Accepts both shapes:
 *  - generated (`database/SPECS/schema.sql`): `CREATE TABLE public.t (…)` plus separate
 *    `ALTER TABLE … ADD CONSTRAINT … FOREIGN KEY … REFERENCES public.parent(…)` statements;
 *  - hand-written: inline `col … REFERENCES parent(id)` and in-body
 *    `FOREIGN KEY (…) REFERENCES parent (…)`.
 *
 * Self-references are ignored for ordering (a row may reference its own table with a nullable FK).
 */
export function parseEntityGraph(sql: string): EntityGraph {
  const entities: string[] = []
  const parents: Record<string, string[]> = {}

  // `public.assets` / `"assets"` / `assets` -> `assets`. A qualified name is the generated form.
  const bare = (raw: string) => raw.replace(/["`]/g, '').split('.').pop() as string

  // Split into `CREATE TABLE [IF NOT EXISTS] <name> ( <body> )` blocks.
  const tableRe =
    /CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([\w."`]+)\s*\(([\s\S]*?)\)\s*;/gi
  let m: RegExpExecArray | null
  while ((m = tableRe.exec(sql)) !== null) {
    const name = bare(m[1])
    const body = m[2]
    entities.push(name)
    const refs = new Set<string>()
    const refRe = /REFERENCES\s+([\w."`]+)/gi
    let r: RegExpExecArray | null
    while ((r = refRe.exec(body)) !== null) {
      const parent = bare(r[1])
      if (parent !== name) refs.add(parent) // ignore self-refs for ordering
    }
    parents[name] = [...refs]
  }

  // Foreign keys declared AFTER the table, which is how a generated schema always renders them.
  const alterRe =
    /ALTER\s+TABLE\s+(?:ONLY\s+)?([\w."`]+)[\s\S]*?FOREIGN\s+KEY\s*\([^)]*\)\s*REFERENCES\s+([\w."`]+)/gi
  let a: RegExpExecArray | null
  while ((a = alterRe.exec(sql)) !== null) {
    const child = bare(a[1])
    const parent = bare(a[2])
    if (!parents[child] || child === parent) continue
    if (!parents[child].includes(parent)) parents[child].push(parent)
  }

  // Keep only edges between in-scope entities.
  const inScope = new Set(entities)
  for (const e of entities) parents[e] = parents[e].filter((p) => inScope.has(p))

  // Kahn topological sort, leaves (no unresolved parents) first.
  const createOrder: string[] = []
  const remaining = new Set(entities)
  const resolved = new Set<string>()
  let progress = true
  while (remaining.size && progress) {
    progress = false
    for (const e of [...remaining]) {
      if (parents[e].every((p) => resolved.has(p))) {
        createOrder.push(e)
        resolved.add(e)
        remaining.delete(e)
        progress = true
      }
    }
  }
  return { entities, parents, createOrder, cycles: [...remaining] }
}
