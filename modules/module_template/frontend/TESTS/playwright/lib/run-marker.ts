// The marker one spec file stamps on every row it creates, and the test of whether a row is its own.
// Force-synced with the harness; see rules/testing-guidelines.md § "CRUD E2E tests".
//
// WHY A RANDOM SUFFIX. The marker used to be `E2E-<Date.now() in base 36>`. Two spec files loaded in the
// same millisecond got the SAME marker, and a file's cleanup deletes "the rows whose name starts with my
// marker" — so one file deleted, or failed to delete (a 500: another file's note still pointed at the
// row), rows the other was using. A full run failed that way once and passed on rerun. Thirty-two random
// bits on top of the time make a shared marker impossible in practice.
//
// WHY A BOUNDARY. `startsWith(marker)` also matches a marker that merely begins with this one. A row is
// the spec's own when its name is the marker, or the marker followed by something that is not a letter
// or digit (` Alpha`, `-name`) — never by more marker.
import { randomBytes } from 'node:crypto'

/** A marker no other spec file, in this run or another, shares: `E2E-<time><8 hex digits>`. */
export function newRunMarker(): string {
  return `E2E-${Date.now().toString(36)}${randomBytes(4).toString('hex')}`
}

/** Whether `name` was created by the spec whose marker is `run`. */
export function ownedBy(run: string, name: unknown): boolean {
  if (typeof name !== 'string' || !name.startsWith(run)) return false
  return name.length === run.length || !/[A-Za-z0-9]/.test(name[run.length])
}
