import path from 'path'
import { defineConfig, loadEnv } from '@rsbuild/core'
import { pluginReact } from '@rsbuild/plugin-react'
import { pluginModuleFederation } from '@module-federation/rsbuild-plugin'

const { publicVars } = loadEnv({ prefixes: ['VITE_'] })

export default defineConfig({
  plugins: [
    pluginReact(),
    pluginModuleFederation({
      name: 'template',
      exposes: {
        './moduleManifest': './src/moduleManifest.ts',
      },
      shared: {
        react: { singleton: true, requiredVersion: '^19.2.0' },
        'react-dom': { singleton: true, requiredVersion: '^19.2.0' },
        'react-router-dom': { singleton: true, requiredVersion: '^7.18.0' },
      },
    }),
  ],
  source: {
    entry: {
      index: './src/main.tsx',
    },
    define: {
      ...publicVars,
      // Dev-only Widget Examples gallery gate. Default true (local build includes
      // the gallery); the registry-publish path builds with WIDGET_EXAMPLES=false
      // so the gallery — and its heavy deps (Recharts) — are tree-shaken out.
      __WIDGET_EXAMPLES__: JSON.stringify(process.env.WIDGET_EXAMPLES !== 'false'),
    },
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
      // Dedupe React to this module's single copy. The shared @ideable/ui is linked
      // via a `file:` dep whose own node_modules can carry a different react/react-dom
      // patch; without this, standalone/dev builds can load two React copies and throw
      // "Incompatible React versions". Harmless in the Docker image (one react there),
      // required for standalone dev + headless UI tests.
      react: path.resolve(__dirname, './node_modules/react'),
      'react-dom': path.resolve(__dirname, './node_modules/react-dom'),
    },
  },
  output: {
    assetPrefix: '/remotes/template/',
  },
  dev: {
    assetPrefix: '/remotes/template/',
  },
  html: {
    template: './index.html',
  },
  server: {
    port: Number(process.env.PORT ?? 3001),
    host: '0.0.0.0',
  },
})
