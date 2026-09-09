import * as React from "react"
import { Slot } from "@radix-ui/react-slot"
import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "../lib/utils"

const buttonVariants = cva(
  "ideable:inline-flex ideable:items-center ideable:justify-center ideable:whitespace-nowrap ideable:rounded-md ideable:text-sm ideable:font-medium ideable:ring-offset-background ideable:transition-colors ideable:focus-visible:outline-none ideable:focus-visible:ring-2 ideable:focus-visible:ring-ring ideable:focus-visible:ring-offset-2 ideable:disabled:pointer-events-none ideable:disabled:opacity-50",
  {
    variants: {
      variant: {
        default: "ideable:bg-primary ideable:text-primary-foreground ideable:hover:bg-primary/90",
        destructive:
          "ideable:bg-destructive ideable:text-destructive-foreground ideable:hover:bg-destructive/90",
        outline:
          "ideable:border ideable:border-input ideable:bg-background ideable:hover:bg-accent ideable:hover:text-accent-foreground",
        secondary:
          "ideable:bg-secondary ideable:text-secondary-foreground ideable:hover:bg-secondary/80",
        ghost: "ideable:hover:bg-accent ideable:hover:text-accent-foreground",
        link: "ideable:text-primary ideable:underline-offset-4 ideable:hover:underline",
      },
      size: {
        default: "ideable:h-10 ideable:px-4 ideable:py-2",
        sm: "ideable:h-9 ideable:rounded-md ideable:px-3",
        lg: "ideable:h-11 ideable:rounded-md ideable:px-8",
        icon: "ideable:h-10 ideable:w-10",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
)

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : "button"
    return (
      <Comp
        className={cn(buttonVariants({ variant, size, className }))}
        ref={ref}
        {...props}
      />
    )
  }
)
Button.displayName = "Button"

export { Button, buttonVariants }
