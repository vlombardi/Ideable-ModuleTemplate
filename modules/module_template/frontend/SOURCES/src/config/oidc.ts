/**
 * Environment configuration for module_template frontend
 * Provides runtime environment variable access
 */

// Runtime environment from window.__ENV__ (injected by docker-entrypoint.sh)
declare global {
  interface Window {
    __ENV__?: Record<string, string>
  }
}

/**
 * Get environment variable value
 * Checks runtime window.__ENV__ first, then falls back to import.meta.env
 */
export function getEnv(key: string, defaultValue?: string): string {
  // Try runtime environment first (set by docker-entrypoint.sh)
  if (typeof window !== 'undefined' && window.__ENV__?.[key]) {
    return window.__ENV__[key]
  }

  // Fallback to build-time environment
  const buildEnv = (import.meta as any).env?.[key]
  if (buildEnv) {
    return buildEnv
  }

  if (defaultValue !== undefined) {
    return defaultValue
  }

  throw new Error(`Environment variable ${key} is not defined`)
}

/**
 * OIDC configuration using runtime environment variables
 */
export const oidcConfig = {
  authority: getEnv('VITE_OIDC_AUTHORITY', 'https://mydomain.com/application/o/ideable/'),
  client_id: getEnv('VITE_OIDC_CLIENT_ID', 'ideable-client'),
  redirect_uri: getEnv('VITE_OIDC_REDIRECT_URI', 'https://mydomain.com/auth/callback'),
  post_logout_redirect_uri: getEnv('VITE_OIDC_POST_LOGOUT_REDIRECT_URI', 'https://mydomain.com'),
  response_type: 'code',
  scope: 'openid profile email',
  automaticSilentRenew: false, // Required: Authentik blocks iframe-based renewal
}

export default oidcConfig
