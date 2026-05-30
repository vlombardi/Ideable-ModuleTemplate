const moduleManifest = {
  name: 'Module Template',
  slug: 'template',
  order: 0,
  menuItems: [
    {
      name: 'Items',
      href: '/template/items',
      icon: 'Package',
      order: 0,
    },
  ],
  routes: [
    {
      path: '/items',
      component: () => import('./pages/TemplateItems'),
    },
  ],
  permissions: [
    'template.items:view',
    'template.items:edit',
  ],
}

export default moduleManifest
