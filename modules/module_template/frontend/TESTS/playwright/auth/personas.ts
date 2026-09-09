// E2E login personas. Because Authentik has no password/ROPC grant, headless auth is
// done by driving the real Authentik login form (Playwright is a browser) as a real,
// profile-bearing user — NOT via a service-account token (a machine identity resolves
// no profile). Each persona maps to an Authentik user with a known password and a
// distinct profile/role/permission set, so tests can assert authorization behaviour.
//
// Add a persona here + declare the matching account in a module's `config/test-users.yaml`
// with the profile you want to test. Never point one at a production account.
export interface Persona {
  username: string
  password: string
}

const env = (name: string, fallback?: string): string | undefined => {
  const v = process.env[name]
  return v && v.trim() ? v.trim() : fallback
}

export const PERSONAS: Record<string, Persona> = {
  // Dedicated e2e accounts from `config/test-users.yaml`, provisioned only when
  // E2E_TEST_USERS_ENABLED=true and the execution mode is not prod. They share one password
  // (E2E_TEST_PASSWORD) because they are all non-production identities.
  //
  // Deliberately NOT sadmin. Driving the suite as the bootstrap superadmin was wrong twice over:
  // it is a production account, and it holds every permission — so a suite built around it can
  // only ever assert that something is ALLOWED. Half of authorization is denial, and denial needs
  // a persona that legitimately lacks the permission. Hence three personas differing by exactly
  // what they may do:
  //
  //   hostAdmin     admin             everything, host_app and every module
  //   moduleAdmin   template_admin    Items visible, viewable, EDITABLE
  //   moduleReader  template_reader   Items visible and viewable, NOT editable
  //   noModule      reader            Items hidden and refused
  //   officer       security_officer  can read the privileged-access review; hostAdmin cannot
  hostAdmin: {
    username: env('E2E_ADMIN_USER', 'e2e_admin')!,
    password: env('E2E_ADMIN_PASSWORD', env('E2E_TEST_PASSWORD'))!,
  },
  moduleAdmin: {
    username: env('E2E_MODULE_ADMIN_USER', 'e2e_module_admin')!,
    password: env('E2E_MODULE_ADMIN_PASSWORD', env('E2E_TEST_PASSWORD'))!,
  },
  moduleReader: {
    username: env('E2E_MODULE_READER_USER', 'e2e_module_reader')!,
    password: env('E2E_MODULE_READER_PASSWORD', env('E2E_TEST_PASSWORD'))!,
  },
  noModule: {
    username: env('E2E_NO_MODULE_USER', 'e2e_no_module')!,
    password: env('E2E_NO_MODULE_PASSWORD', env('E2E_TEST_PASSWORD'))!,
  },
  officer: {
    username: env('E2E_OFFICER_USER', 'e2e_officer')!,
    password: env('E2E_OFFICER_PASSWORD', env('E2E_TEST_PASSWORD'))!,
  },
}

// The existing specs ran as sadmin, which held everything; `hostAdmin` is the
// equivalent capability on a disposable identity, so they keep working unchanged.
export const DEFAULT_PERSONA = 'hostAdmin'

export function hasCreds(p?: Persona): boolean {
  return !!(p && p.username && p.password)
}
