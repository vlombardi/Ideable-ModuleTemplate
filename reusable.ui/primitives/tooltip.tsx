import * as React from "react"
import * as TooltipPrimitive from "@radix-ui/react-tooltip"
import { cn } from "../lib/utils"

const TooltipProvider = TooltipPrimitive.Provider

const Tooltip = TooltipPrimitive.Root

const TooltipTrigger = TooltipPrimitive.Trigger

const TooltipContent = React.forwardRef<
  React.ElementRef<typeof TooltipPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof TooltipPrimitive.Content>
>(({ className, sideOffset = 4, ...props }, ref) => (
  <TooltipPrimitive.Content
    ref={ref}
    sideOffset={sideOffset}
    className={cn(
      "ideable:z-50 ideable:overflow-hidden ideable:rounded-md ideable:border ideable:bg-popover ideable:px-3 ideable:py-1.5 ideable:text-sm ideable:text-popover-foreground ideable:shadow-md ideable:animate-in ideable:fade-in-0 ideable:zoom-in-95 ideable:data-[state=closed]:animate-out ideable:data-[state=closed]:fade-out-0 ideable:data-[state=closed]:zoom-out-95 ideable:data-[side=bottom]:slide-in-from-top-2 ideable:data-[side=left]:slide-in-from-right-2 ideable:data-[side=right]:slide-in-from-left-2 ideable:data-[side=top]:slide-in-from-bottom-2",
      className
    )}
    {...props}
  />
))
TooltipContent.displayName = TooltipPrimitive.Content.displayName

export { Tooltip, TooltipTrigger, TooltipContent, TooltipProvider }
