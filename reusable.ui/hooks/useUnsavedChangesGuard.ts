import { useCallback, useEffect, useState } from 'react'

export interface UnsavedChangesGuardAction {
  onDiscard: () => void | Promise<void>
  onSave?: () => void | Promise<void>
  onKeepEditing?: () => void
}

export interface UnsavedChangesGuardOptions {
  dirty: boolean
  enabled?: boolean
}

export interface UnsavedChangesGuardResult {
  isPromptOpen: boolean
  requestGuardedAction: (action: UnsavedChangesGuardAction) => void
  handleKeepEditing: () => void
  handleDiscard: () => Promise<void>
  handleSave: () => Promise<void>
}

export function useUnsavedChangesGuard(hasUnsavedChanges: boolean): UnsavedChangesGuardResult
export function useUnsavedChangesGuard(options: UnsavedChangesGuardOptions): UnsavedChangesGuardResult
export function useUnsavedChangesGuard(
  input: boolean | UnsavedChangesGuardOptions,
): UnsavedChangesGuardResult {
  const dirty = typeof input === 'boolean' ? input : input.dirty
  const enabled = typeof input === 'boolean' ? true : input.enabled ?? true
  const [isPromptOpen, setIsPromptOpen] = useState(false)
  const [pendingAction, setPendingAction] = useState<UnsavedChangesGuardAction | null>(null)

  useEffect(() => {
    const handleBeforeUnload = (event: BeforeUnloadEvent) => {
      if (!enabled || !dirty) {
        return
      }

      event.preventDefault()
      event.returnValue = ''
    }

    window.addEventListener('beforeunload', handleBeforeUnload)
    return () => window.removeEventListener('beforeunload', handleBeforeUnload)
  }, [dirty, enabled])

  const requestGuardedAction = useCallback(
    (action: UnsavedChangesGuardAction) => {
      if (!enabled || !dirty) {
        void action.onDiscard()
        return
      }

      setPendingAction(action)
      setIsPromptOpen(true)
    },
    [dirty, enabled],
  )

  const handleKeepEditing = useCallback(() => {
    pendingAction?.onKeepEditing?.()
    setPendingAction(null)
    setIsPromptOpen(false)
  }, [pendingAction])

  const handleDiscard = useCallback(async () => {
    const action = pendingAction
    setPendingAction(null)
    setIsPromptOpen(false)
    if (action) {
      await action.onDiscard()
    }
  }, [pendingAction])

  const handleSave = useCallback(async () => {
    const action = pendingAction
    setPendingAction(null)
    setIsPromptOpen(false)
    if (action?.onSave) {
      await action.onSave()
      return
    }
    if (action) {
      await action.onDiscard()
    }
  }, [pendingAction])

  return {
    isPromptOpen,
    requestGuardedAction,
    handleKeepEditing,
    handleDiscard,
    handleSave,
  }
}
