// Build-time constant injected via rsbuild `source.define` from the WIDGET_EXAMPLES
// build arg. When false (registry-publish builds), the dev-only Widget Examples
// gallery and its heavy deps are dead-code-eliminated from the bundle.
declare const __WIDGET_EXAMPLES__: boolean
