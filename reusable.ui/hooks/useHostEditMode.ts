import { useEffect, useState } from "react"

/** Where host_app records the shell-wide edit toggle. */
const STORAGE_KEY = "hostapp.edit_mode"

/**
 * Whether the host shell is in edit mode.
 *
 * The toggle lives in host_app's chrome, not in a module's page: one switch for the whole shell, so
 * a user turns editing on once rather than per screen. A module page only observes it.
 *
 * Observed three ways because there are three ways it changes, and a page that listened to fewer
 * would be right only some of the time: the custom event when the shell toggles it in this tab, the
 * `storage` event when another tab does, and a read on mount for a page opened with it already on.
 *
 * In the library because every entity page needs exactly this, and a copy per page is a copy that
 * drifts — the version in `module_template` was already the third.
 */
export function useHostEditMode(): boolean {
  const [editMode, setEditMode] = useState<boolean>(() => {
    try {
      return window.localStorage.getItem(STORAGE_KEY) === "true"
    } catch {
      // A blocked or absent localStorage is not an error here: the honest default is "not editing",
      // which shows a read-only page rather than offering actions that may not be permitted.
      return false
    }
  })

  useEffect(() => {
    const read = () => {
      try {
        setEditMode(window.localStorage.getItem(STORAGE_KEY) === "true")
      } catch {
        setEditMode(false)
      }
    }

    const onModeChanged = (event: Event) => {
      const detail = (event as CustomEvent<{ isEditMode?: boolean }>).detail
      if (typeof detail?.isEditMode === "boolean") {
        setEditMode(detail.isEditMode)
        return
      }
      read()
    }

    const onStorage = (event: StorageEvent) => {
      if (event.key === STORAGE_KEY) read()
    }

    window.addEventListener("hostapp:edit-mode-changed", onModeChanged)
    window.addEventListener("storage", onStorage)
    return () => {
      window.removeEventListener("hostapp:edit-mode-changed", onModeChanged)
      window.removeEventListener("storage", onStorage)
    }
  }, [])

  return editMode
}
