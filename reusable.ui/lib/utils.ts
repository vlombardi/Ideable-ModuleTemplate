import { type ClassValue, clsx } from 'clsx'
import { extendTailwindMerge } from 'tailwind-merge'

// tailwind-merge configured for the shared `ideable` prefix so conflicting
// `ideable:` utility classes merge correctly inside @ideable/ui widgets/primitives.
const twMerge = extendTailwindMerge({ prefix: 'ideable' })

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}
