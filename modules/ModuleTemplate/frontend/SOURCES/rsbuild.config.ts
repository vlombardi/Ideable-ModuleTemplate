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
        react: { singleton: true, requiredVersion: '^18.2.0' },
        'react-dom': { singleton: true, requiredVersion: '^18.2.0' },
        'react-router-dom': { singleton: true, requiredVersion: '^6.21.1' },
      },
    }),
  ],
  source: {
    entry: {
      index: './src/main.tsx',
    },
    define: publicVars,
    alias: {
      '@': path.resolve(__dirname, './src'),
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
