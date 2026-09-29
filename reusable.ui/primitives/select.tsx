import * as React from "react"
import * as SelectPrimitive from "@radix-ui/react-select"
import { Check, ChevronDown, ChevronUp } from "lucide-react"
import { cn } from "../lib/utils"

const Select = SelectPrimitive.Root
const SelectGroup = SelectPrimitive.Group
const SelectValue = SelectPrimitive.Value

const SelectTrigger = React.forwardRef<
  React.ElementRef<typeof SelectPrimitive.Trigger>,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.Trigger>
>(({ className, children, ...props }, ref) => (
  <SelectPrimitive.Trigger
    ref={ref}
    className={cn(
      "ideable:flex ideable:h-10 ideable:w-full ideable:items-center ideable:justify-between ideable:rounded-md ideable:border ideable:border-input ideable:bg-background ideable:px-3 ideable:py-2 ideable:text-sm ideable:ring-offset-background ideable:placeholder:text-muted-foreground ideable:focus:outline-none ideable:focus:ring-2 ideable:focus:ring-ring ideable:focus:ring-offset-2 ideable:disabled:cursor-not-allowed ideable:disabled:opacity-50 ideable:[&>span]:line-clamp-1",
      className
    )}
    {...props}
  >
    {children}
    <SelectPrimitive.Icon asChild>
      <ChevronDown className="ideable:h-4 ideable:w-4 ideable:opacity-50" />
    </SelectPrimitive.Icon>
  </SelectPrimitive.Trigger>
))
SelectTrigger.displayName = SelectPrimitive.Trigger.displayName

const SelectScrollUpButton = React.forwardRef<
  React.ElementRef<typeof SelectPrimitive.ScrollUpButton>,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.ScrollUpButton>
>(({ className, ...props }, ref) => (
  <SelectPrimitive.ScrollUpButton
    ref={ref}
    className={cn(
      "ideable:flex ideable:cursor-default ideable:items-center ideable:justify-center ideable:py-1",
      className
    )}
    {...props}
  >
    <ChevronUp className="ideable:h-4 ideable:w-4" />
  </SelectPrimitive.ScrollUpButton>
))
SelectScrollUpButton.displayName = SelectPrimitive.ScrollUpButton.displayName

const SelectScrollDownButton = React.forwardRef<
  React.ElementRef<typeof SelectPrimitive.ScrollDownButton>,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.ScrollDownButton>
>(({ className, ...props }, ref) => (
  <SelectPrimitive.ScrollDownButton
    ref={ref}
    className={cn(
      "ideable:flex ideable:cursor-default ideable:items-center ideable:justify-center ideable:py-1",
      className
    )}
    {...props}
  >
    <ChevronDown className="ideable:h-4 ideable:w-4" />
  </SelectPrimitive.ScrollDownButton>
))
SelectScrollDownButton.displayName =
  SelectPrimitive.ScrollDownButton.displayName

const SelectContent = React.forwardRef<
  React.ElementRef<typeof SelectPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.Content>
>(({ className, children, position = "popper", ...props }, ref) => (
  <SelectPrimitive.Portal>
    <SelectPrimitive.Content
      ref={ref}
      className={cn(
        "ideable:relative ideable:z-50 ideable:max-h-96 ideable:min-w-[8rem] ideable:overflow-hidden ideable:rounded-md ideable:border ideable:bg-popover ideable:text-popover-foreground ideable:shadow-md ideable:data-[state=open]:animate-in ideable:data-[state=closed]:animate-out ideable:data-[state=closed]:fade-out-0 ideable:data-[state=open]:fade-in-0 ideable:data-[state=closed]:zoom-out-95 ideable:data-[state=open]:zoom-in-95 ideable:data-[side=bottom]:slide-in-from-top-2 ideable:data-[side=left]:slide-in-from-right-2 ideable:data-[side=right]:slide-in-from-left-2 ideable:data-[side=top]:slide-in-from-bottom-2",
        position === "popper" &&
          "ideable:data-[side=bottom]:translate-y-1 data-[side=left]:ideable:-translate-x-1 ideable:data-[side=right]:translate-x-1 data-[side=top]:ideable:-translate-y-1",
        className
      )}
      position={position}
      {...props}
    >
      <SelectScrollUpButton />
      <SelectPrimitive.Viewport
        className={cn(
          "ideable:p-1",
          position === "popper" &&
            "ideable:h-[var(--radix-select-trigger-height)] ideable:w-full ideable:min-w-[var(--radix-select-trigger-width)]"
        )}
      >
        {children}
      </SelectPrimitive.Viewport>
      <SelectScrollDownButton />
    </SelectPrimitive.Content>
  </SelectPrimitive.Portal>
))
SelectContent.displayName = SelectPrimitive.Content.displayName

const SelectLabel = React.forwardRef<
  React.ElementRef<typeof SelectPrimitive.Label>,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.Label>
>(({ className, ...props }, ref) => (
  <SelectPrimitive.Label
    ref={ref}
    className={cn("ideable:py-1.5 ideable:pl-8 ideable:pr-2 ideable:text-sm ideable:font-semibold", className)}
    {...props}
  />
))
SelectLabel.displayName = SelectPrimitive.Label.displayName

const SelectItem = React.forwardRef<
  React.ElementRef<typeof SelectPrimitive.Item>,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.Item>
>(({ className, children, ...props }, ref) => (
  <SelectPrimitive.Item
    ref={ref}
    className={cn(
      "ideable:relative ideable:flex ideable:w-full ideable:cursor-default ideable:select-none ideable:items-center ideable:rounded-sm ideable:py-1.5 ideable:pl-8 ideable:pr-2 ideable:text-sm ideable:outline-none ideable:focus:bg-accent ideable:focus:text-accent-foreground ideable:data-[disabled]:pointer-events-none ideable:data-[disabled]:opacity-50",
      className
    )}
    {...props}
  >
    <span className="ideable:absolute ideable:left-2 ideable:flex ideable:h-3.5 ideable:w-3.5 ideable:items-center ideable:justify-center">
      <SelectPrimitive.ItemIndicator>
        <Check className="ideable:h-4 ideable:w-4" />
      </SelectPrimitive.ItemIndicator>
    </span>
    <SelectPrimitive.ItemText>{children}</SelectPrimitive.ItemText>
  </SelectPrimitive.Item>
))
SelectItem.displayName = SelectPrimitive.Item.displayName

const SelectSeparator = React.forwardRef<
  React.ElementRef<typeof SelectPrimitive.Separator>,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.Separator>
>(({ className, ...props }, ref) => (
  <SelectPrimitive.Separator
    ref={ref}
    className={cn("ideable:-mx-1 ideable:my-1 ideable:h-px ideable:bg-muted", className)}
    {...props}
  />
))
SelectSeparator.displayName = SelectPrimitive.Separator.displayName

export {
  Select,
  SelectGroup,
  SelectValue,
  SelectTrigger,
  SelectContent,
  SelectLabel,
  SelectItem,
  SelectSeparator,
  SelectScrollUpButton,
  SelectScrollDownButton,
}
