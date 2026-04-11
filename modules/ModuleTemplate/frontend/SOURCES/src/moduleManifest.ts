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
    'template.items.read',
    'template.items.create',
    'template.items.update',
    'template.items.delete',
  ],
}

export default moduleManifest
