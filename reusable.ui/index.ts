// @ideable/ui — Ideable framework shared UI widget library.
// Widgets are styled with the neutral `ideable:` CSS prefix and design tokens;
// import "@ideable/ui/styles" once in each consumer to load the token + utility layer.
export * from './widgets/index'
export * from './primitives/index'
export { useTranslation, registerModuleMessages } from './hooks/useTranslation'
export { useServerTableState } from './hooks/useServerTableState'
export { useEntityQuery } from './hooks/useEntityQuery'
export { useHostEditMode } from './hooks/useHostEditMode'
export type {
  EntityDescriptor,
  EntityPage,
  EntityTransport,
  UseEntityQueryOptions,
  UseEntityQueryResult,
} from './hooks/useEntityQuery'
export { useUnsavedChangesGuard } from './hooks/useUnsavedChangesGuard'
export type {
  UnsavedChangesGuardAction,
  UnsavedChangesGuardOptions,
  UnsavedChangesGuardResult,
} from './hooks/useUnsavedChangesGuard'
