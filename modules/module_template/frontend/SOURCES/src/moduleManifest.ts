// Side-effect import: makes the `./moduleManifest` Module-Federation expose carry this
// module's compiled stylesheet (the `ideable:` widget layer + this module's `<slug>:` layer
// + `.<slug>-scope` token cascade) in its `assets.css`. When host_app calls
// `loadRemote('<slug>/moduleManifest')`, the MF runtime auto-injects the CSS <link> before
// the manifest resolves, so the module renders styled inside host_app — without relying on
// the standalone `main.tsx`/`bootstrap.tsx` chain. Deduplicated against bootstrap.tsx's own
// import; standalone builds are unaffected. See module-integration-specs.md §2 (CSS loading
// contract) and frontend-css-and-dependency-implementation-plan.md §B.
import './index.css'

const menuItems = [
  {
    name: 'Items',
    href: '/template/items',
    icon: 'Package',
    order: 0,
  },
]

const routes = [
  {
    path: '/items',
    component: () => import('./pages/TemplateItems'),
  },
]

// Dev-only Widget Examples gallery route: registered in local builds, and
// dead-code-eliminated (route + page + heavy deps) from registry-publish builds
// where WIDGET_EXAMPLES=false. The sidebar entry lives under the Template menu in
// modules_menu_mapping.json / menu_definition.json (nested next to Items).
if (__WIDGET_EXAMPLES__) {
  routes.push({
    path: '/gallery',
    component: () => import('./pages/WidgetGallery'),
  })
}

const moduleManifest = {
  name: 'Module Template',
  slug: 'template',
  order: 0,
  menuItems,
  routes,
  permissions: [
    'items:view',
    'items:edit',
  ],
}

export default moduleManifest
