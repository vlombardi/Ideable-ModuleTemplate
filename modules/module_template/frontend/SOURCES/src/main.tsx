// Module Federation async boundary. The remote shares react / react-dom /
// react-router-dom as singletons; importing them synchronously at the entry
// triggers `loadShareSync` before the MF runtime has initialized the share scope,
// which throws when the remote runs standalone (no host to seed the scope). The
// dynamic import defers all shared-module loading past runtime init, so the app
// mounts both inside host_app and standalone (dev server / headless UI tests).
// Note: this file is only the standalone HTML entry — host_app consumes the remote
// via the exposed `./moduleManifest`, so this boundary does not affect consumption.
import('./bootstrap')
