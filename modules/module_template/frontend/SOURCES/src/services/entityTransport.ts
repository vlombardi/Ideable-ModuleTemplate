/**
 * How `@ideable/ui`'s entity widgets reach THIS module's API.
 *
 * The one thing a module supplies to use the standard page: the widgets take a transport rather
 * than a typed service, which is what lets one `StandardEntityPage` serve every entity a module
 * declares — including entities added later, with no frontend code written for them.
 *
 * Auth, the base URL and the error mapping stay here because they are the module's, not the
 * library's: `@ideable/ui` must not know how a module authenticates or where its API lives.
 */
import { getEnv } from '@/config/oidc'
import { getCurrentAccessToken } from './authToken'
import type { AuditPageParams, EntityTransport } from '@ideable/ui'

const API_BASE_URL = getEnv('VITE_TEMPLATE_API_URL', '/module/template/api')

export class EntityTransportError extends Error {
  constructor(message: string, public status: number) {
    super(message)
    this.name = 'EntityTransportError'
  }
}

function queryString(params?: Record<string, unknown>): string {
  if (!params) return ''
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    // Undefined and null are ABSENT, not empty: `?name=` filters on the empty string, which is a
    // different question from "do not filter by name".
    if (value === undefined || value === null || value === '') continue
    search.append(key, String(value))
  }
  const rendered = search.toString()
  return rendered ? `?${rendered}` : ''
}

async function call(path: string, init: RequestInit = {}): Promise<Response> {
  const token = getCurrentAccessToken()
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...((init.headers as Record<string, string>) || {}),
  }
  if (token) headers['Authorization'] = `Bearer ${token}`

  const response = await fetch(`${API_BASE_URL}${path}`, { ...init, headers })
  if (!response.ok) {
    if (response.status === 401) {
      // The same signal the module's own services raise, so a session expiring under a standard
      // page is handled by the one listener that already exists.
      window.dispatchEvent(new CustomEvent('auth:session-expired'))
      throw new EntityTransportError('Session expired', response.status)
    }
    throw new EntityTransportError(
      `API Error: ${response.status} - ${await response.text()}`,
      response.status,
    )
  }
  return response
}

/**
 * Flattens `AuditPageParams` (the audit popup's own shape, with `filters` as a nested object)
 * into the flat query params `entityTransport.get` sends over the wire.
 *
 * `templateItemsService.getHistoryPage` does this same flattening by hand for the one entity that
 * has a dedicated service (`items`). Entities served ONLY through `entityTransport` — every entity
 * added after `items`, per `shared-ui-widgets-specs.md` § *Main entities definition* — need it too
 * to wire `StandardEntityPage`'s `fetchHistoryPage`, so it lives here rather than being copied
 * into each page.
 */
export function historyQueryParams(params: AuditPageParams): Record<string, unknown> {
  const flat: Record<string, unknown> = {
    skip: params.skip,
    limit: params.limit,
    sort_by: params.sort_by,
    sort_order: params.sort_order,
  }
  for (const [key, value] of Object.entries(params.filters ?? {})) {
    if (value && value.trim() !== '') flat[key] = value
  }
  return flat
}

export const entityTransport: EntityTransport = {
  async get(path: string, params?: Record<string, unknown>): Promise<unknown> {
    return (await call(`${path}${queryString(params)}`)).json()
  },
  async post(path: string, body: unknown): Promise<unknown> {
    return (await call(path, { method: 'POST', body: JSON.stringify(body) })).json()
  },
  async put(path: string, body: unknown): Promise<unknown> {
    return (await call(path, { method: 'PUT', body: JSON.stringify(body) })).json()
  },
  async delete(path: string): Promise<void> {
    // 204 No Content: nothing to parse, and calling .json() on it would throw.
    await call(path, { method: 'DELETE' })
  },
}
