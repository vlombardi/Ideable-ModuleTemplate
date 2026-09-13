import * as React from "react"
import { cn } from "../lib/utils"

export interface InputProps
  extends React.InputHTMLAttributes<HTMLInputElement> {}

const Input = React.forwardRef<HTMLInputElement, InputProps>(
  ({ className, type, ...props }, ref) => {
    return (
      <input
        type={type}
        className={cn(
          "ideable:flex ideable:h-10 ideable:w-full ideable:rounded-md ideable:border ideable:border-input ideable:bg-background ideable:px-3 ideable:py-2 ideable:text-sm ideable:ring-offset-background ideable:file:border-0 ideable:file:bg-transparent ideable:file:text-sm ideable:file:font-medium ideable:placeholder:text-muted-foreground ideable:focus-visible:outline-none ideable:focus-visible:ring-2 ideable:focus-visible:ring-ring ideable:focus-visible:ring-offset-2 ideable:disabled:cursor-not-allowed ideable:disabled:opacity-50",
          className
        )}
        ref={ref}
        {...props}
      />
    )
  }
)
Input.displayName = "Input"

export { Input }
