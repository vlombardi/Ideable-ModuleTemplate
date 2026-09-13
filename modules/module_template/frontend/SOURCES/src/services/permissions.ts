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
 *
 * The answer carries an OUTCOME beside the set, because the same empty set arrives for three
 * different reasons and they are not the same thing to say to a user. An empty set meant "not
 * authorized" no matter what happened, so a session whose token had expired — and a host_app that
 * answered 503 while authorization was unavailable — both rendered a denial the user could do
 * nothing about and could not diagnose. That is how the stale-token defect in `authToken.ts` reached
 * the browser as "You are not authorized to view this page".
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
 * Why the permission set is what it is.
 *
 * - `ok` — host_app answered; the set is this user's real permissions, empty or not. Only this
 *   outcome licenses saying "not authorized".
 * - `session-expired` — there is no usable token, or host_app rejected the one sent (401). Says
 *   nothing about what the user may do; they need to sign in again.
 * - `unavailable` — host_app could not answer (503, or the request never completed). Also says
 *   nothing about what the user may do.
 */
export type PermissionOutcome = 'ok' | 'session-expired' | 'unavailable'

export interface PermissionResult {
  permissions: Set<string>
  outcome: PermissionOutcome
}

const failed = (outcome: Exclude<PermissionOutcome, 'ok'>): PermissionResult => ({
  permissions: new Set<string>(),
  outcome,
})

/**
 * The permissions the current user holds right now, with the reason when they could not be resolved.
 *
 * Every failure yields an EMPTY set, and that is deliberate and fail-closed: the UI hides what it
 * cannot prove the user may do. An empty set must never be read as "the user has no permissions"
 * unless `outcome` is `ok` — the backend makes the actual authorization decision, and a caller that
 * renders a denial on any other outcome tells the user something this function did not establish.
 */
export const fetchPermissions = async (): Promise<PermissionResult> => {
  const token = getCurrentAccessToken()
  if (!token) return failed('session-expired')

  try {
    const response = await fetch(`${HOSTAPP_API_BASE_URL.replace(/\/$/, '')}/me`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    if (response.status === 401) return failed('session-expired')
    if (!response.ok) return failed('unavailable')
    const body = (await response.json()) as MeResponse
    return {
      permissions: new Set(
        (body.permissions ?? []).filter((p): p is string => typeof p === 'string' && p.length > 0),
      ),
      outcome: 'ok',
    }
  } catch {
    return failed('unavailable')
  }
}
