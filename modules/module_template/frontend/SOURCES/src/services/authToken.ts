import { getEnv } from '@/config/oidc'

const OIDC_USER_KEY_PREFIX = 'oidc.user:'

const normalizeAuthority = (authority: string): string => authority.replace(/\/+$/, '')

const buildExpectedOidcUserKey = (): string => {
  const authority = normalizeAuthority(getEnv('VITE_OIDC_AUTHORITY'))
  const clientId = getEnv('VITE_OIDC_CLIENT_ID')
  return `${OIDC_USER_KEY_PREFIX}${authority}:${clientId}`
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

export const getCurrentAccessToken = (): string | null => {
  const expectedKey = buildExpectedOidcUserKey()
  const directValue = readSessionStorageValue(expectedKey)
  if (directValue) {
    try {
      const parsed = JSON.parse(directValue) as { access_token?: unknown }
      if (typeof parsed.access_token === 'string' && parsed.access_token.trim()) {
        return parsed.access_token.trim()
      }
    } catch {
      // fall through to scan for the current OIDC user entry
    }
  }

  if (typeof window === 'undefined') {
    return null
  }

  for (let index = 0; index < window.sessionStorage.length; index += 1) {
    const key = window.sessionStorage.key(index)
    if (!key || !key.startsWith(OIDC_USER_KEY_PREFIX)) {
      continue
    }

    const raw = readSessionStorageValue(key)
    if (!raw) {
      continue
    }

    try {
      const parsed = JSON.parse(raw) as { access_token?: unknown }
      if (typeof parsed.access_token === 'string' && parsed.access_token.trim()) {
        return parsed.access_token.trim()
      }
    } catch {
      continue
    }
  }

  return null
}
