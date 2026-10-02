import { test, expect } from '@playwright/test'
import { newRunMarker, ownedBy } from '../lib/run-marker'

// Stack-free unit test for the run-marker helper the CRUD specs stamp their rows with and clean up by.
// Runs in every test phase (no auth / no running stack).

test.describe('run marker', () => {
  test('two markers made in the same millisecond differ', () => {
    const markers = new Set(Array.from({ length: 2000 }, () => newRunMarker()))
    expect(markers.size).toBe(2000)
  })

  test('a marker has the E2E prefix, a time part and a random part', () => {
    expect(newRunMarker()).toMatch(/^E2E-[0-9a-z]{6,}[0-9a-f]{8}$/)
  })

  test('a row is owned by the marker that is its name, or that precedes a non-alphanumeric boundary', () => {
    const run = newRunMarker()
    expect(ownedBy(run, run)).toBe(true)
    expect(ownedBy(run, `${run} Alpha`)).toBe(true)
    expect(ownedBy(run, `${run}-name`)).toBe(true)
    expect(ownedBy(run, `${run}-name-upd`)).toBe(true)
  })

  test('a row of another marker is not owned, even when this marker is a prefix of that one', () => {
    const run = newRunMarker()
    expect(ownedBy(run, `${run}0 Alpha`)).toBe(false)
    expect(ownedBy(run, `${run}abc`)).toBe(false)
    expect(ownedBy(run, newRunMarker())).toBe(false)
    expect(ownedBy(run, 'Sample Item')).toBe(false)
  })

  test('a name that is not a string is not owned', () => {
    expect(ownedBy('E2E-x', undefined)).toBe(false)
    expect(ownedBy('E2E-x', null)).toBe(false)
    expect(ownedBy('E2E-x', 42)).toBe(false)
  })
})
