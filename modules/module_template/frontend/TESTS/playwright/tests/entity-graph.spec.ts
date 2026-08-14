import { test, expect } from '@playwright/test'
import { parseEntityGraph } from '../lib/entity-graph'

// Stack-free unit test for the FK dependency-tree helper used by FK-aware CRUD specs.
// Runs in every test phase (no auth / no running stack).

const SQL = `
CREATE TABLE IF NOT EXISTS company ( id serial PRIMARY KEY, name text );
CREATE TABLE IF NOT EXISTS asset (
  id serial PRIMARY KEY,
  company_id integer NOT NULL,
  FOREIGN KEY (company_id) REFERENCES company (id)
);
CREATE TABLE IF NOT EXISTS map (
  id serial PRIMARY KEY,
  asset_id integer REFERENCES asset(id),
  parent_map_id integer REFERENCES map(id)  -- self-ref, ignored for ordering
);
`

test.describe('entity-graph — FK dependency tree', () => {
  test('records parents and orders leaves before dependents', () => {
    const g = parseEntityGraph(SQL)
    expect([...g.entities].sort()).toEqual(['asset', 'company', 'map'])
    expect(g.parents.asset).toEqual(['company'])
    expect(g.parents.map).toEqual(['asset']) // self-ref to map is dropped
    expect(g.cycles).toEqual([])
    // company (leaf) before asset before map
    expect(g.createOrder.indexOf('company')).toBeLessThan(g.createOrder.indexOf('asset'))
    expect(g.createOrder.indexOf('asset')).toBeLessThan(g.createOrder.indexOf('map'))
  })
})
