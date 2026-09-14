/**
 * The access token of the CURRENT session, read from where oidc-client-ts put it.
 *
 * host_app owns the OIDC session; a remote module never mints a token, it reads the one the host
 * stored. That read has to name the entry exactly, and this file is written the way it is because it
 * once did not. The key was built by stripping the authority's trailing slash, while oidc-client-ts
 * writes `oidc.user:${authority}:${client_id}` with the authority VERBATIM — and the documented
 * Authentik authority ends in `/`. So the direct lookup matched in no deployment at all, every call
 * fell through to a scan that returned the FIRST `oidc.user:` entry sessionStorage happened to
 * yield, and a leftover entry from an earlier session handed host_app a token whose signing key
 * Authentik no longer publishes. host_app answered 401, the permission fetch failed closed, and a
 * fully authorized user was told they were not authorized to view the page.
 *
 * Three rules follow, one per step of that chain:
 *  1. Address the entry as the library wrote it — the authority verbatim, both slash forms tried,
 *     because nothing guarantees which form a deployment's templating leaves in the variable.
 *  2. Never return a token issued to a different authority or client. An entry belonging to another
 *     session is not a worse answer than none; it is a wrong one.
 *  3. Never return an expired token. It buys a 401 that reads, downstream, as a denial.
 */

import { getEnv } from '@/config/oidc'

/** oidc-client-ts stores the user under `${prefix}user:${authority}:${client_id}`, prefix `oidc.`. */
const OIDC_USER_KEY_PREFIX = 'oidc.user:'

interface StoredOidcUser {
  access_token?: unknown
  expires_at?: unknown
}

/** `getEnv` throws when a variable is unset, and an absent OIDC config is not an exception here. */
const readEnv = (key: string): string | null => {
  try {
    const value = getEnv(key).trim()
    return value ? value : null
  } catch {
    return null
  }
}

const readSessionStorageValue = (key: string): string | null => {
  if (typeof window === 'undefined') {
    return null
  }

  try {
    return window.sessionStorage.getItem(key)
  } catch {
    return null
  }
}

/**
 * The authority in both slash forms, the configured one first.
 *
 * The stored key carries whatever string was handed to `UserManager`, so the configured value is the
 * best candidate; the other form is tried because host_app and a module read the authority from the
 * same variable but the trailing slash is not guaranteed to survive every deployment's templating.
 */
const authorityKeyVariants = (authority: string): string[] => {
  const bare = authority.replace(/\/+$/, '')
  return authority === bare ? [bare, `${bare}/`] : [authority, bare]
}

/** The usable access token in a stored entry, or `null` when it holds none worth sending. */
const usableAccessToken = (raw: string | null): string | null => {
  if (!raw) {
    return null
  }

  let parsed: StoredOidcUser
  try {
    parsed = JSON.parse(raw) as StoredOidcUser
  } catch {
    return null
  }

  const token = parsed.access_token
  if (typeof token !== 'string' || !token.trim()) {
    return null
  }

  // `expires_at` is seconds since the epoch (oidc-client-ts). An expired token earns a 401 that the
  // caller cannot tell apart from a permission denial, so an expired entry is treated as no entry.
  if (typeof parsed.expires_at === 'number' && parsed.expires_at * 1000 <= Date.now()) {
    return null
  }

  return token.trim()
}

export const getCurrentAccessToken = (): string | null => {
  if (typeof window === 'undefined') {
    return null
  }

  const authority = readEnv('VITE_OIDC_AUTHORITY')
  const clientId = readEnv('VITE_OIDC_CLIENT_ID')

  // The current session, addressed exactly as the library wrote it. While the authority and client
  // are known this is the ONLY acceptable answer: an entry under any other key was issued to another
  // session, and sending its token is the defect this file documents.
  if (authority && clientId) {
    for (const variant of authorityKeyVariants(authority)) {
      const token = usableAccessToken(
        readSessionStorageValue(`${OIDC_USER_KEY_PREFIX}${variant}:${clientId}`),
      )
      if (token) {
        return token
      }
    }
    return null
  }

  // The OIDC configuration is unavailable — a standalone render with no injected `window.__ENV__` —
  // so the entry cannot be named. Scan, but refuse to guess: one unexpired candidate is the session;
  // several are ambiguous, and picking one of several is precisely the old bug.
  const candidates: string[] = []
  for (let index = 0; index < window.sessionStorage.length; index += 1) {
    const key = window.sessionStorage.key(index)
    if (!key || !key.startsWith(OIDC_USER_KEY_PREFIX)) {
      continue
    }

    const token = usableAccessToken(readSessionStorageValue(key))
    if (token) {
      candidates.push(token)
    }
  }

  return candidates.length === 1 ? candidates[0] : null
}
