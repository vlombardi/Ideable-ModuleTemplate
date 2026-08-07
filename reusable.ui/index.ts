// @ideable/ui — Ideable framework shared UI widget library.
// Widgets are styled with the neutral `ideable:` CSS prefix and design tokens;
// import "@ideable/ui/styles" once in each consumer to load the token + utility layer.
export * from './widgets/index'
export * from './primitives/index'
export { useTranslation } from './hooks/useTranslation'
export { useServerTableState } from './hooks/useServerTableState'
export { useUnsavedChangesGuard } from './hooks/useUnsavedChangesGuard'
export type {
  UnsavedChangesGuardAction,
  UnsavedChangesGuardOptions,
  UnsavedChangesGuardResult,
} from './hooks/useUnsavedChangesGuard'
