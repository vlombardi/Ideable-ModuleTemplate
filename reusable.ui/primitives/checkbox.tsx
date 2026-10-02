import * as React from "react"
import * as CheckboxPrimitive from "@radix-ui/react-checkbox"
import { Check } from "lucide-react"
import { cn } from "../lib/utils"

const Checkbox = React.forwardRef<
  React.ElementRef<typeof CheckboxPrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof CheckboxPrimitive.Root>
>(({ className, ...props }, ref) => (
  <CheckboxPrimitive.Root
    ref={ref}
    className={cn(
      "ideable:peer ideable:h-4 ideable:w-4 ideable:shrink-0 ideable:rounded-sm ideable:border ideable:border-primary ideable:ring-offset-background ideable:focus-visible:outline-none ideable:focus-visible:ring-2 ideable:focus-visible:ring-ring ideable:focus-visible:ring-offset-2 ideable:disabled:cursor-not-allowed ideable:disabled:opacity-50 ideable:data-[state=checked]:bg-primary ideable:data-[state=checked]:text-primary-foreground",
      className
    )}
    {...props}
  >
    <CheckboxPrimitive.Indicator
      className={cn("ideable:flex ideable:items-center ideable:justify-center ideable:text-current")}
    >
      <Check className="ideable:h-4 ideable:w-4" />
    </CheckboxPrimitive.Indicator>
  </CheckboxPrimitive.Root>
))
Checkbox.displayName = CheckboxPrimitive.Root.displayName

export { Checkbox }
