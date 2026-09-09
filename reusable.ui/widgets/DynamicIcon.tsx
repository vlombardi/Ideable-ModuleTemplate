import type { ComponentType } from 'react'
import * as LucideIcons from 'lucide-react'
import type { LucideProps } from 'lucide-react'

interface DynamicIconProps extends LucideProps {
  name: string
}

const iconMap = LucideIcons as unknown as Record<string, ComponentType<LucideProps>>

export function DynamicIcon({ name, ...props }: DynamicIconProps) {
  const Icon = iconMap[name] ?? LucideIcons.Circle
  return <Icon {...props} />
}
