import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "../primitives/dialog"
import { Button } from "../primitives/button"

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
  return (
    <Dialog open={open} onOpenChange={(isOpen) => !isOpen && onKeepEditing()}>
      <DialogContent className="ideable:sm:max-w-[425px]">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        <DialogFooter className="ideable:flex ideable:flex-wrap ideable:gap-2">
          <Button
            variant="outline"
            onClick={onKeepEditing}
          >
            {keepEditingLabel}
          </Button>
          <Button
            variant="outline"
            onClick={() => {
              void onDiscard()
            }}
          >
            {discardLabel}
          </Button>
          {onSave && saveLabel ? (
            <Button
              onClick={() => {
                void onSave()
              }}
            >
              {saveLabel}
            </Button>
          ) : null}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
