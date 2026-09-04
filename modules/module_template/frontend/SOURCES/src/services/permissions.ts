/**
 * The remote module's permission source: host_app's `/me`.
 *
 * The access token is THIN — it carries identity and tenant ids, not permissions. A
 * remote frontend that decodes the token therefore finds nothing and hides its own pages, which is
 * exactly the regression this file exists to prevent: `TemplateItems.tsx` derived `canView` from the
 * token and started answering "You are not authorized to view this page" to a user who was fully
 * authorized.
 *
 * Every remote module derived from this template must use this, not the token. The permission set is
 * resolved server-side by host_app from its own authorization tables, arrives already fully
 * qualified as `<module_slug>.<resource>:<action>`, and reflects the user's ACTIVE profile — so a
 * profile switch takes effect on the next fetch rather than at the next token issue.
 */

import { getEnv } from '@/config/oidc'
import { getCurrentAccessToken } from './authToken'

/** host_app's API, same origin behind the reverse proxy. */
const HOSTAPP_API_BASE_URL = getEnv('VITE_API_URL', '/api')

export interface MeResponse {
  username: string
  permissions: string[]
  active_profile: string | null
}

/**
 * The permissions the current user holds right now, or an EMPTY set when they cannot be determined.
 *
 * Empty-on-failure is deliberate and it is fail-closed: the UI hides what it cannot prove the user
 * may do. It must never be read as "the user has no permissions" for any purpose other than hiding
 * UI — the backend makes the actual authorization decision and answers 503 when it cannot.
 */
export const fetchPermissions = async (): Promise<Set<string>> => {
  const token = getCurrentAccessToken()
  if (!token) return new Set<string>()

  try {
    const response = await fetch(`${HOSTAPP_API_BASE_URL.replace(/\/$/, '')}/me`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    if (!response.ok) return new Set<string>()
    const body = (await response.json()) as MeResponse
    return new Set(
      (body.permissions ?? []).filter((p): p is string => typeof p === 'string' && p.length > 0),
    )
  } catch {
    return new Set<string>()
  }
}
