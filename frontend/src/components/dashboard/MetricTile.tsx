import type { LucideIcon } from 'lucide-react'
import { Card, CardBody } from '@/components/ui/card'
import { cn, metricOrDash } from '@/lib/utils'

type Accent = 'docs' | 'chunks' | 'latency' | 'queue' | 'neutral'

const accentClass: Record<Accent, string> = {
  docs: 'text-metric-docs bg-action-soft',
  chunks: 'text-metric-chunks bg-status-info-soft',
  latency: 'text-metric-latency bg-status-info-soft',
  queue: 'text-metric-queue bg-status-warn-soft',
  neutral: 'text-ink-secondary bg-panel-muted',
}

export function MetricTile({
  label,
  value,
  hint,
  icon: Icon,
  accent = 'neutral',
  className,
}: {
  label: string
  value: string | number | null | undefined
  hint?: string
  icon?: LucideIcon
  accent?: Accent
  className?: string
}) {
  return (
    <Card className={cn('h-full', className)}>
      <CardBody className="flex h-full flex-col justify-between gap-3 p-4">
        <div className="flex items-start justify-between gap-2">
          <p className="text-xs font-semibold uppercase tracking-wide text-ink-subtle">
            {label}
          </p>
          {Icon && (
            <span
              className={cn(
                'inline-flex h-8 w-8 items-center justify-center rounded-md',
                accentClass[accent],
              )}
            >
              <Icon className="h-4 w-4" aria-hidden />
            </span>
          )}
        </div>
        <div>
          <p className="text-3xl font-semibold tracking-tight text-ink tabular-nums">
            {metricOrDash(value)}
          </p>
          {hint && <p className="mt-1 text-xs text-ink-secondary">{hint}</p>}
        </div>
      </CardBody>
    </Card>
  )
}
