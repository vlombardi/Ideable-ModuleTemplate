// E2E login personas. Because Authentik has no password/ROPC grant, headless auth is
// done by driving the real Authentik login form (Playwright is a browser) as a real,
// profile-bearing user — NOT via a service-account token (a machine identity resolves
// no profile). Each persona maps to an Authentik user with a known password and a
// distinct profile/role/permission set, so tests can assert authorization behaviour.
//
// Add a persona here + ensure the matching user exists in Authentik
// (modules/host_app/config/authorization.yaml) with the profile you want to test.
export interface Persona {
  username: string
  password: string
}

const env = (name: string, fallback?: string): string | undefined => {
  const v = process.env[name]
  return v && v.trim() ? v.trim() : fallback
}

export const PERSONAS: Record<string, Persona> = {
  // Standard "can see everything" persona — the bootstrap superadmin user (active
  // profile: admin). Credentials come from the deployment env (SADMIN_* /
  // AUTHENTIK_BOOTSTRAP_*), overridable with E2E_STANDARD_*.
  standard: {
    username: env('E2E_STANDARD_USER', env('SADMIN_USERNAME', 'sadmin'))!,
    password: env('E2E_STANDARD_PASSWORD', env('SADMIN_PASSWORD', env('AUTHENTIK_BOOTSTRAP_PASSWORD')))!,
  },
  // Future profile-scoped personas (real profile-bearing users). Uncomment + provide
  // creds when the corresponding authz test cases are added:
  // reader: { username: env('E2E_READER_USER', 'guest')!, password: env('E2E_READER_PASSWORD')! },
  // officer: { username: env('E2E_OFFICER_USER', 'template_admin')!, password: env('E2E_OFFICER_PASSWORD')! },
}

export const DEFAULT_PERSONA = 'standard'

export function hasCreds(p?: Persona): boolean {
  return !!(p && p.username && p.password)
}
