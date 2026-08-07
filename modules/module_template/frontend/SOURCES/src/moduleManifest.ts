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
