import { Card, CardBody, CardHeader, CardTitle } from '@/components/ui/card'
import { metricOrDash } from '@/lib/utils'

/** Placeholder analytics until eval / ask metrics APIs exist. */
export function AnalyticsStrip({
  hitAt1,
  mrr,
  leakRate,
  p95Ms,
}: {
  hitAt1?: string | number | null
  mrr?: string | number | null
  leakRate?: string | number | null
  p95Ms?: string | number | null
}) {
  const rows = [
    { label: 'Hit@1', value: hitAt1, hint: 'Retrieval quality' },
    { label: 'MRR', value: mrr, hint: 'Rank quality' },
    { label: 'Leak rate', value: leakRate, hint: 'Access attacks' },
    { label: 'p95 latency', value: p95Ms, hint: 'Ask path' },
  ]

  return (
    <Card className="h-full">
      <CardHeader>
        <CardTitle>Quality & latency</CardTitle>
        <span className="text-[10px] font-semibold uppercase tracking-wide text-ink-subtle">
          Eval / live
        </span>
      </CardHeader>
      <CardBody className="grid grid-cols-2 gap-3 pt-0 sm:grid-cols-4">
        {rows.map((row) => (
          <div
            key={row.label}
            className="rounded-md border border-line bg-panel-muted/50 px-3 py-3"
          >
            <p className="text-[11px] font-semibold uppercase tracking-wide text-ink-subtle">
              {row.label}
            </p>
            <p className="mt-1 text-xl font-semibold tabular-nums text-ink">
              {metricOrDash(row.value)}
            </p>
            <p className="mt-0.5 text-[11px] text-ink-secondary">{row.hint}</p>
          </div>
        ))}
      </CardBody>
    </Card>
  )
}
