import * as React from "react"
import * as TabsPrimitive from "@radix-ui/react-tabs"
import { cn } from "../lib/utils"

const Tabs = TabsPrimitive.Root

const TabsList = React.forwardRef<
  React.ElementRef<typeof TabsPrimitive.List>,
  React.ComponentPropsWithoutRef<typeof TabsPrimitive.List>
>(({ className, ...props }, ref) => (
  <TabsPrimitive.List
    ref={ref}
    className={cn(
      "ideable:inline-flex ideable:h-10 ideable:items-center ideable:justify-center ideable:rounded-md ideable:bg-muted ideable:p-1 ideable:text-muted-foreground",
      className
    )}
    {...props}
  />
))
TabsList.displayName = TabsPrimitive.List.displayName

const TabsTrigger = React.forwardRef<
  React.ElementRef<typeof TabsPrimitive.Trigger>,
  React.ComponentPropsWithoutRef<typeof TabsPrimitive.Trigger>
>(({ className, ...props }, ref) => (
  <TabsPrimitive.Trigger
    ref={ref}
    className={cn(
      "ideable:inline-flex ideable:items-center ideable:justify-center ideable:whitespace-nowrap ideable:rounded-sm ideable:px-3 ideable:py-1.5 ideable:text-sm ideable:font-medium ideable:ring-offset-background ideable:transition-all ideable:focus-visible:outline-none ideable:focus-visible:ring-2 ideable:focus-visible:ring-ring ideable:focus-visible:ring-offset-2 ideable:disabled:pointer-events-none ideable:disabled:opacity-50 ideable:data-[state=active]:bg-background ideable:data-[state=active]:text-foreground ideable:data-[state=active]:shadow-sm",
      className
    )}
    {...props}
  />
))
TabsTrigger.displayName = TabsPrimitive.Trigger.displayName

const TabsContent = React.forwardRef<
  React.ElementRef<typeof TabsPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof TabsPrimitive.Content>
>(({ className, ...props }, ref) => (
  <TabsPrimitive.Content
    ref={ref}
    className={cn(
      "ideable:mt-2 ideable:ring-offset-background ideable:focus-visible:outline-none ideable:focus-visible:ring-2 ideable:focus-visible:ring-ring ideable:focus-visible:ring-offset-2",
      className
    )}
    {...props}
  />
))
TabsContent.displayName = TabsPrimitive.Content.displayName

export { Tabs, TabsList, TabsTrigger, TabsContent }
