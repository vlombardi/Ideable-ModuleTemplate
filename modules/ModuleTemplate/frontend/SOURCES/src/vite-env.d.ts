/// <reference types="@rsbuild/core/types" />

interface ImportMetaEnv {
  readonly VITE_APP_TITLE: string
  readonly VITE_TEMPLATE_API_URL: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
