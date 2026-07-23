import React from 'react'

interface UnsavedChangesDialogProps {
  open: boolean
  title: string
  description: string
  keepEditingLabel: string
  discardLabel: string
  saveLabel?: string
  onKeepEditing: () => void
  onDiscard: () => void | Promise<void>
  onSave?: () => void | Promise<void>
}

export function UnsavedChangesDialog({
  open,
  title,
  description,
  keepEditingLabel,
  discardLabel,
  saveLabel,
  onKeepEditing,
  onDiscard,
  onSave,
}: UnsavedChangesDialogProps) {
  if (!open) {
    return null
  }

  return (
    <div className="template:fixed template:inset-0 template:z-50 template:flex template:items-center template:justify-center template:bg-black/40 template:p-4">
      <div className="template:w-full template:max-w-md template:rounded-lg template:bg-background template:p-6 template:shadow-lg template:space-y-4">
        <div className="template:space-y-2">
          <h2 className="template:text-lg template:font-semibold">{title}</h2>
          <p className="template:text-sm template:text-muted-foreground">{description}</p>
        </div>
        <div className="template:flex template:flex-wrap template:justify-end template:gap-2">
          <button
            type="button"
            onClick={onKeepEditing}
            className="template:inline-flex template:items-center template:justify-center template:rounded-md template:border template:border-input template:bg-background template:px-4 template:py-2 template:text-sm template:font-medium template:shadow-sm template:transition-colors template:hover:bg-accent template:hover:text-accent-foreground"
          >
            {keepEditingLabel}
          </button>
          <button
            type="button"
            onClick={() => {
              void onDiscard()
            }}
            className="template:inline-flex template:items-center template:justify-center template:rounded-md template:border template:border-input template:bg-background template:px-4 template:py-2 template:text-sm template:font-medium template:shadow-sm template:transition-colors template:hover:bg-accent template:hover:text-accent-foreground"
          >
            {discardLabel}
          </button>
          {onSave && saveLabel ? (
            <button
              type="button"
              onClick={() => {
                void onSave()
              }}
              className="template:inline-flex template:items-center template:justify-center template:rounded-md template:bg-primary template:px-4 template:py-2 template:text-sm template:font-medium template:text-primary-foreground template:shadow-sm template:transition-colors template:hover:bg-primary/90"
            >
              {saveLabel}
            </button>
          ) : null}
        </div>
      </div>
    </div>
  )
}
