import * as React from "react"
import * as DropdownMenuPrimitive from "@radix-ui/react-dropdown-menu"
import { Check, ChevronRight, Circle } from "lucide-react"
import { cn } from "../lib/utils"

const DropdownMenu = DropdownMenuPrimitive.Root
const DropdownMenuTrigger = DropdownMenuPrimitive.Trigger
const DropdownMenuGroup = DropdownMenuPrimitive.Group
const DropdownMenuPortal = DropdownMenuPrimitive.Portal
const DropdownMenuSub = DropdownMenuPrimitive.Sub
const DropdownMenuRadioGroup = DropdownMenuPrimitive.RadioGroup

const DropdownMenuSubTrigger = React.forwardRef<
  React.ElementRef<typeof DropdownMenuPrimitive.SubTrigger>,
  React.ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.SubTrigger> & {
    inset?: boolean
  }
>(({ className, inset, children, ...props }, ref) => (
  <DropdownMenuPrimitive.SubTrigger
    ref={ref}
    className={cn(
      "ideable:flex ideable:cursor-default ideable:select-none ideable:items-center ideable:rounded-sm ideable:px-2 ideable:py-1.5 ideable:text-sm ideable:outline-none ideable:focus:bg-accent ideable:data-[state=open]:bg-accent",
      inset && "ideable:pl-8",
      className
    )}
    {...props}
  >
    {children}
    <ChevronRight className="ideable:ml-auto ideable:h-4 ideable:w-4" />
  </DropdownMenuPrimitive.SubTrigger>
))
DropdownMenuSubTrigger.displayName =
  DropdownMenuPrimitive.SubTrigger.displayName

const DropdownMenuSubContent = React.forwardRef<
  React.ElementRef<typeof DropdownMenuPrimitive.SubContent>,
  React.ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.SubContent>
>(({ className, ...props }, ref) => (
  <DropdownMenuPrimitive.SubContent
    ref={ref}
    className={cn(
      "ideable:z-50 ideable:min-w-[8rem] ideable:overflow-hidden ideable:rounded-md ideable:border ideable:bg-popover ideable:p-1 ideable:text-popover-foreground ideable:shadow-lg ideable:data-[state=open]:animate-in ideable:data-[state=closed]:animate-out ideable:data-[state=closed]:fade-out-0 ideable:data-[state=open]:fade-in-0 ideable:data-[state=closed]:zoom-out-95 ideable:data-[state=open]:zoom-in-95 ideable:data-[side=bottom]:slide-in-from-top-2 ideable:data-[side=left]:slide-in-from-right-2 ideable:data-[side=right]:slide-in-from-left-2 ideable:data-[side=top]:slide-in-from-bottom-2",
      className
    )}
    {...props}
  />
))
DropdownMenuSubContent.displayName =
  DropdownMenuPrimitive.SubContent.displayName

const DropdownMenuContent = React.forwardRef<
  React.ElementRef<typeof DropdownMenuPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.Content>
>(({ className, sideOffset = 4, ...props }, ref) => (
  <DropdownMenuPrimitive.Portal>
    <DropdownMenuPrimitive.Content
      ref={ref}
      sideOffset={sideOffset}
      className={cn(
        "ideable:z-50 ideable:min-w-[8rem] ideable:overflow-hidden ideable:rounded-md ideable:border ideable:bg-popover ideable:p-1 ideable:text-popover-foreground ideable:shadow-md ideable:data-[state=open]:animate-in ideable:data-[state=closed]:animate-out ideable:data-[state=closed]:fade-out-0 ideable:data-[state=open]:fade-in-0 ideable:data-[state=closed]:zoom-out-95 ideable:data-[state=open]:zoom-in-95 ideable:data-[side=bottom]:slide-in-from-top-2 ideable:data-[side=left]:slide-in-from-right-2 ideable:data-[side=right]:slide-in-from-left-2 ideable:data-[side=top]:slide-in-from-bottom-2",
        className
      )}
      {...props}
    />
  </DropdownMenuPrimitive.Portal>
))
DropdownMenuContent.displayName = DropdownMenuPrimitive.Content.displayName

const DropdownMenuItem = React.forwardRef<
  React.ElementRef<typeof DropdownMenuPrimitive.Item>,
  React.ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.Item> & {
    inset?: boolean
  }
>(({ className, inset, ...props }, ref) => (
  <DropdownMenuPrimitive.Item
    ref={ref}
    className={cn(
      "ideable:relative ideable:flex ideable:cursor-default ideable:select-none ideable:items-center ideable:rounded-sm ideable:px-2 ideable:py-1.5 ideable:text-sm ideable:outline-none ideable:transition-colors ideable:focus:bg-accent ideable:focus:text-accent-foreground ideable:data-[disabled]:pointer-events-none ideable:data-[disabled]:opacity-50",
      inset && "ideable:pl-8",
      className
    )}
    {...props}
  />
))
DropdownMenuItem.displayName = DropdownMenuPrimitive.Item.displayName

const DropdownMenuCheckboxItem = React.forwardRef<
  React.ElementRef<typeof DropdownMenuPrimitive.CheckboxItem>,
  React.ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.CheckboxItem>
>(({ className, children, checked, ...props }, ref) => (
  <DropdownMenuPrimitive.CheckboxItem
    ref={ref}
    className={cn(
      "ideable:relative ideable:flex ideable:cursor-default ideable:select-none ideable:items-center ideable:rounded-sm ideable:py-1.5 ideable:pl-8 ideable:pr-2 ideable:text-sm ideable:outline-none ideable:transition-colors ideable:focus:bg-accent ideable:focus:text-accent-foreground ideable:data-[disabled]:pointer-events-none ideable:data-[disabled]:opacity-50",
      className
    )}
    checked={checked}
    {...props}
  >
    <span className="ideable:absolute ideable:left-2 ideable:flex ideable:h-3.5 ideable:w-3.5 ideable:items-center ideable:justify-center">
      <DropdownMenuPrimitive.ItemIndicator>
        <Check className="ideable:h-4 ideable:w-4" />
      </DropdownMenuPrimitive.ItemIndicator>
    </span>
    {children}
  </DropdownMenuPrimitive.CheckboxItem>
))
DropdownMenuCheckboxItem.displayName =
  DropdownMenuPrimitive.CheckboxItem.displayName

const DropdownMenuRadioItem = React.forwardRef<
  React.ElementRef<typeof DropdownMenuPrimitive.RadioItem>,
  React.ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.RadioItem>
>(({ className, children, ...props }, ref) => (
  <DropdownMenuPrimitive.RadioItem
    ref={ref}
    className={cn(
      "ideable:relative ideable:flex ideable:cursor-default ideable:select-none ideable:items-center ideable:rounded-sm ideable:py-1.5 ideable:pl-8 ideable:pr-2 ideable:text-sm ideable:outline-none ideable:transition-colors ideable:focus:bg-accent ideable:focus:text-accent-foreground ideable:data-[disabled]:pointer-events-none ideable:data-[disabled]:opacity-50",
      className
    )}
    {...props}
  >
    <span className="ideable:absolute ideable:left-2 ideable:flex ideable:h-3.5 ideable:w-3.5 ideable:items-center ideable:justify-center">
      <DropdownMenuPrimitive.ItemIndicator>
        <Circle className="ideable:h-2 ideable:w-2 ideable:fill-current" />
      </DropdownMenuPrimitive.ItemIndicator>
    </span>
    {children}
  </DropdownMenuPrimitive.RadioItem>
))
DropdownMenuRadioItem.displayName = DropdownMenuPrimitive.RadioItem.displayName

const DropdownMenuLabel = React.forwardRef<
  React.ElementRef<typeof DropdownMenuPrimitive.Label>,
  React.ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.Label> & {
    inset?: boolean
  }
>(({ className, inset, ...props }, ref) => (
  <DropdownMenuPrimitive.Label
    ref={ref}
    className={cn(
      "ideable:px-2 ideable:py-1.5 ideable:text-sm ideable:font-semibold",
      inset && "ideable:pl-8",
      className
    )}
    {...props}
  />
))
DropdownMenuLabel.displayName = DropdownMenuPrimitive.Label.displayName

const DropdownMenuSeparator = React.forwardRef<
  React.ElementRef<typeof DropdownMenuPrimitive.Separator>,
  React.ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.Separator>
>(({ className, ...props }, ref) => (
  <DropdownMenuPrimitive.Separator
    ref={ref}
    className={cn("ideable:-mx-1 ideable:my-1 ideable:h-px ideable:bg-muted", className)}
    {...props}
  />
))
DropdownMenuSeparator.displayName = DropdownMenuPrimitive.Separator.displayName

const DropdownMenuShortcut = ({
  className,
  ...props
}: React.HTMLAttributes<HTMLSpanElement>) => {
  return (
    <span
      className={cn("ideable:ml-auto ideable:text-xs ideable:tracking-widest ideable:opacity-60", className)}
      {...props}
    />
  )
}
DropdownMenuShortcut.displayName = "DropdownMenuShortcut"

export {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuCheckboxItem,
  DropdownMenuRadioItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuShortcut,
  DropdownMenuGroup,
  DropdownMenuPortal,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuRadioGroup,
}
