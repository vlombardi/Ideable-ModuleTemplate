// Entity dependency-tree helper for FK-aware CRUD E2E tests. Parses a module's
// datamodel.sql into a foreign-key dependency graph and a topological (leaf-first)
// order, so generated CRUD specs can CREATE parents before children (valorizing FK
// fields) and DELETE in reverse. Force-synced with the harness; see
// rules/testing-guidelines.md § "CRUD E2E tests — Foreign-key ordering".

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
 * Parse a datamodel.sql (PostgreSQL) into an FK dependency graph.
 * Handles table FK constraints (`FOREIGN KEY (...) REFERENCES parent (...)`) and inline
 * column references (`col ... REFERENCES parent(...)`). Self-references are ignored for
 * ordering (a row can reference its own table with a nullable FK).
 */
export function parseEntityGraph(sql: string): EntityGraph {
  const entities: string[] = []
  const parents: Record<string, string[]> = {}

  // Split into `CREATE TABLE [IF NOT EXISTS] <name> ( <body> )` blocks.
  const tableRe = /CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?["`]?(\w+)["`]?\s*\(([\s\S]*?)\)\s*;/gi
  let m: RegExpExecArray | null
  while ((m = tableRe.exec(sql)) !== null) {
    const name = m[1]
    const body = m[2]
    entities.push(name)
    const refs = new Set<string>()
    const refRe = /REFERENCES\s+["`]?(\w+)["`]?/gi
    let r: RegExpExecArray | null
    while ((r = refRe.exec(body)) !== null) {
      if (r[1] !== name) refs.add(r[1]) // ignore self-refs for ordering
    }
    parents[name] = [...refs]
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
