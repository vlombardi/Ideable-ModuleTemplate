import * as React from "react"
import * as DialogPrimitive from "@radix-ui/react-dialog"
import { X } from "lucide-react"
import { cn } from "../lib/utils"

const Dialog = DialogPrimitive.Root
const DialogTrigger = DialogPrimitive.Trigger
const DialogPortal = DialogPrimitive.Portal
const DialogClose = DialogPrimitive.Close

const DialogOverlay = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Overlay>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Overlay>
>(({ className, ...props }, ref) => (
  <DialogPrimitive.Overlay
    ref={ref}
    className={cn(
      "ideable:fixed ideable:inset-0 ideable:z-50 ideable:bg-black/80 ideable:data-[state=open]:animate-in ideable:data-[state=closed]:animate-out ideable:data-[state=closed]:fade-out-0 ideable:data-[state=open]:fade-in-0",
      className
    )}
    {...props}
  />
))
DialogOverlay.displayName = DialogPrimitive.Overlay.displayName

const DialogContent = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Content>
>(({ className, children, ...props }, ref) => (
  <DialogPortal>
    <DialogOverlay />
    <DialogPrimitive.Content
      ref={ref}
      className={cn(
        "ideable:fixed ideable:left-[50%] ideable:top-[50%] ideable:z-50 ideable:grid ideable:w-full ideable:max-w-lg ideable:max-h-[calc(100vh-2rem)] ideable:overflow-y-auto ideable:translate-x-[-50%] ideable:translate-y-[-50%] ideable:gap-4 ideable:border ideable:bg-white ideable:p-6 ideable:shadow-lg ideable:duration-200 ideable:data-[state=open]:animate-in ideable:data-[state=closed]:animate-out ideable:data-[state=closed]:fade-out-0 ideable:data-[state=open]:fade-in-0 ideable:data-[state=closed]:zoom-out-95 ideable:data-[state=open]:zoom-in-95 ideable:data-[state=closed]:slide-out-to-left-1/2 ideable:data-[state=closed]:slide-out-to-top-[48%] ideable:data-[state=open]:slide-in-from-left-1/2 ideable:data-[state=open]:slide-in-from-top-[48%] ideable:sm:rounded-lg",
        className
      )}
      {...props}
    >
      {children}
      <DialogPrimitive.Close className="ideable:absolute ideable:right-4 ideable:top-4 ideable:rounded-sm ideable:opacity-70 ideable:ring-offset-background ideable:transition-opacity ideable:hover:opacity-100 ideable:focus:outline-none ideable:focus:ring-2 ideable:focus:ring-ring ideable:focus:ring-offset-2 ideable:disabled:pointer-events-none ideable:data-[state=open]:bg-accent ideable:data-[state=open]:text-muted-foreground">
        <X className="ideable:h-4 ideable:w-4" />
        <span className="ideable:sr-only">Close</span>
      </DialogPrimitive.Close>
    </DialogPrimitive.Content>
  </DialogPortal>
))
DialogContent.displayName = DialogPrimitive.Content.displayName

const DialogHeader = ({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) => (
  <div
    className={cn(
      "ideable:flex ideable:flex-col ideable:space-y-1.5 ideable:text-center ideable:sm:text-left",
      className
    )}
    {...props}
  />
)
DialogHeader.displayName = "DialogHeader"

const DialogFooter = ({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) => (
  <div
    className={cn(
      "ideable:flex ideable:flex-col-reverse ideable:sm:flex-row ideable:sm:justify-end ideable:sm:space-x-2",
      className
    )}
    {...props}
  />
)
DialogFooter.displayName = "DialogFooter"

const DialogTitle = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Title>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Title>
>(({ className, ...props }, ref) => (
  <DialogPrimitive.Title
    ref={ref}
    className={cn(
      "ideable:text-lg ideable:font-semibold ideable:leading-none ideable:tracking-tight",
      className
    )}
    {...props}
  />
))
DialogTitle.displayName = DialogPrimitive.Title.displayName

const DialogDescription = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Description>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Description>
>(({ className, ...props }, ref) => (
  <DialogPrimitive.Description
    ref={ref}
    className={cn("ideable:text-sm ideable:text-muted-foreground", className)}
    {...props}
  />
))
DialogDescription.displayName = DialogPrimitive.Description.displayName

export {
  Dialog,
  DialogPortal,
  DialogOverlay,
  DialogClose,
  DialogTrigger,
  DialogContent,
  DialogHeader,
  DialogFooter,
  DialogTitle,
  DialogDescription,
}
