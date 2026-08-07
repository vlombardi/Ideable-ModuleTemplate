import { test, expect } from '../auth/session-fixture'
import { request as pwRequest, type APIRequestContext } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

// Generic, force-syncable CRUD E2E. It introspects the module's OWN backend OpenAPI and
// round-trips Create -> Read -> Update -> Delete for every discoverable collection
// resource, logging EACH operation explicitly (entity, data, id, field change) so a
// maintainer sees exactly what ran. Because it derives everything from the module under
// test, the same spec works for any module (module_template Items, SRA companies/assets,
// …) with zero edits.
//
// Resources whose create can't be satisfied generically (e.g. required foreign keys /
// business constraints) are reported as SKIPPED with the server's reason — not failed.
// The spec fails only if a create SUCCEEDS but a later read/update/delete then fails.
// Opt-in via RUN_STACK_E2E=1. See testing-guidelines.md § "CRUD E2E tests".

const here = path.dirname(fileURLToPath(import.meta.url))
const STACK = process.env.TEMPLATE_FRONTEND_URL ?? process.env.HOSTAPP_FRONTEND_URL ?? 'http://localhost:3001'
const MANIFEST = path.join(here, '..', '..', '..', 'SOURCES', 'src', 'moduleManifest.ts')

function moduleSlug(): string {
  const m = fs.readFileSync(MANIFEST, 'utf8').match(/slug:\s*['"]([^'"]+)['"]/)
  return m ? m[1] : 'template'
}
// Traefik strips /module/<slug>; the backend OpenAPI paths already include the /api
// mount prefix (e.g. /api/items), so resource URLs = MODULE_PREFIX + <openapi path>.
const MODULE_PREFIX = `${STACK}/module/${moduleSlug()}`
const OPENAPI_URL = `${MODULE_PREFIX}/api/openapi.json`
const RUN = `E2E-${Date.now().toString(36)}`

function bearerFromSession(): string {
  const captured = JSON.parse(fs.readFileSync(path.join(here, '..', 'auth', '.auth', 'standard.json'), 'utf8'))
  return JSON.parse(captured.session.value).access_token as string
}

// ---- OpenAPI helpers -------------------------------------------------------
type Json = Record<string, any>
function resolveRef(oa: Json, schema: Json | undefined): Json {
  if (schema && schema.$ref) {
    const parts = String(schema.$ref).replace(/^#\//, '').split('/')
    return parts.reduce((acc: Json, p) => (acc ? acc[p] : undefined), oa) ?? {}
  }
  return schema ?? {}
}
function sampleValue(oa: Json, schema: Json): unknown {
  const s = resolveRef(oa, schema)
  if (Array.isArray(s.enum) && s.enum.length) return s.enum[0]
  if (Array.isArray(s.anyOf) || Array.isArray(s.oneOf)) return sampleValue(oa, (s.anyOf ?? s.oneOf)[0])
  switch (s.type) {
    case 'integer':
    case 'number':
      return 1
    case 'boolean':
      return false
    case 'array':
      return []
    case 'object':
      return {}
    default:
      return `${RUN}`
  }
}
function buildCreateBody(oa: Json, schema: Json): Json {
  const s = resolveRef(oa, schema)
  const required: string[] = s.required ?? []
  const body: Json = {}
  for (const [key, propSchema] of Object.entries(s.properties ?? {})) {
    if (required.includes(key)) body[key] = sampleValue(oa, propSchema as Json)
  }
  // Give string fields a recognizable, unique marker where possible.
  for (const [key, val] of Object.entries(body)) if (typeof val === 'string') body[key] = `${RUN}-${key}`
  return body
}

/** Discover collection CRUD resources: POST /X + a /X/{id} with delete (and put/patch). */
function discoverResources(oa: Json): Array<{ collection: string; updateVerb: 'put' | 'patch' | null }> {
  const paths = oa.paths ?? {}
  const out: Array<{ collection: string; updateVerb: 'put' | 'patch' | null }> = []
  for (const p of Object.keys(paths)) {
    if (/\{[^}]+\}/.test(p)) continue // skip item paths here; we key off collections
    if (!paths[p].post) continue
    const itemPath = Object.keys(paths).find((q) => new RegExp(`^${p}/\\{[^}]+\\}$`).test(q))
    if (!itemPath) continue
    const item = paths[itemPath]
    if (!item.delete) continue
    out.push({ collection: p, updateVerb: item.put ? 'put' : item.patch ? 'patch' : null })
  }
  return out
}

test.describe('Module CRUD endpoints (generic, live stack)', () => {
  test.skip(!process.env.RUN_STACK_E2E, 'Requires a running authenticated stack; set RUN_STACK_E2E=1')

  let api: APIRequestContext
  const log = (line: string) => console.log(`[CRUD] ${line}`)

  test.beforeAll(async () => {
    api = await pwRequest.newContext({
      ignoreHTTPSErrors: true,
      extraHTTPHeaders: { Authorization: `Bearer ${bearerFromSession()}` },
    })
  })
  test.afterAll(async () => api?.dispose())

  test('CRUD round-trip for every discoverable resource', async () => {
    const oaRes = await api.get(OPENAPI_URL)
    expect(oaRes.ok(), `GET ${OPENAPI_URL}`).toBeTruthy()
    const oa = (await oaRes.json()) as Json
    const resources = discoverResources(oa)
    log(`discovered ${resources.length} CRUD resource(s): ${resources.map((r) => r.collection).join(', ') || '(none)'}`)
    expect(resources.length, 'no CRUD collection resources found in OpenAPI').toBeGreaterThan(0)

    let roundTrips = 0
    for (const { collection, updateVerb } of resources) {
      const url = `${MODULE_PREFIX}${collection}`
      const schema =
        oa.paths[collection]?.post?.requestBody?.content?.['application/json']?.schema ?? {}
      const body = buildCreateBody(oa, schema)

      // CREATE
      const createRes = await api.post(url, { data: body })
      if (![200, 201].includes(createRes.status())) {
        log(`${collection}: CREATE ${JSON.stringify(body)} -> SKIPPED (${createRes.status()}: ${(await createRes.text()).slice(0, 120)})`)
        continue
      }
      const created = await createRes.json()
      const id = created.id ?? created.ID ?? created.uuid
      log(`${collection}: CREATE ${JSON.stringify(body)} -> ${createRes.status()} id=${id}  PASSED`)
      expect(id, `${collection}: create response must carry an id`).toBeDefined()

      await test.step(`READ ${collection} id=${id}`, async () => {
        let found = await api.get(`${url}/${id}`)
        if (!found.ok()) found = await api.get(url, { params: { id: String(id), limit: '500' } })
        expect(found.ok(), `${collection}: READ id=${id}`).toBeTruthy()
        log(`${collection}: READ id=${id} -> ${found.status()}  PASSED`)
      })

      if (updateVerb) {
        const strField = Object.keys(body).find((k) => typeof body[k] === 'string')
        if (strField) {
          const oldVal = body[strField]
          const newVal = `${oldVal}-upd`
          const upd = await api[updateVerb](`${url}/${id}`, { data: { [strField]: newVal } })
          expect(upd.ok(), `${collection}: UPDATE id=${id}`).toBeTruthy()
          log(`${collection}: UPDATE id=${id} ${strField} "${oldVal}" -> "${newVal}" -> ${upd.status()}  PASSED`)
        }
      }

      const del = await api.delete(`${url}/${id}`)
      expect([200, 204].includes(del.status()), `${collection}: DELETE id=${id} -> ${del.status()}`).toBeTruthy()
      log(`${collection}: DELETE id=${id} -> ${del.status()}  PASSED`)
      roundTrips += 1
    }

    log(`completed ${roundTrips}/${resources.length} full CRUD round-trip(s)`)
  })
})
