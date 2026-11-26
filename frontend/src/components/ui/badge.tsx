import type { HTMLAttributes } from 'react'
import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from '@/lib/utils'

const badgeVariants = cva(
  'inline-flex items-center rounded-md border px-2 py-0.5 text-xs font-medium',
  {
    variants: {
      tone: {
        neutral: 'border-line bg-panel-muted text-ink-secondary',
        ok: 'border-transparent bg-status-ok-soft text-status-ok',
        warn: 'border-transparent bg-status-warn-soft text-status-warn',
        bad: 'border-transparent bg-status-bad-soft text-status-bad',
        info: 'border-transparent bg-status-info-soft text-status-info',
        action: 'border-transparent bg-action-soft text-action',
      },
    },
    defaultVariants: { tone: 'neutral' },
  },
)

export interface BadgeProps
  extends HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

export function Badge({ className, tone, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ tone }), className)} {...props} />
}
