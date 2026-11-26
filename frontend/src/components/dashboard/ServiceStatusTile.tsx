import { Activity, CircleAlert, CircleCheck } from 'lucide-react'
import { Card, CardBody, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'

function normalizeState(state: string): 'ok' | 'warn' | 'bad' | 'unknown' {
  const s = state.toLowerCase()
  if (s === 'connected' || s === 'running' || s === 'healthy' || s === 'ok') return 'ok'
  if (s === 'unknown' || s === '—' || s === '-') return 'unknown'
  if (s === 'disconnected' || s === 'down' || s === 'error' || s === 'failed') return 'bad'
  return 'warn'
}

export function ServiceStatusTile({
  services,
  loading,
  error,
  onRetry,
}: {
  services: Record<string, string>
  loading?: boolean
  error?: boolean
  onRetry?: () => void
}) {
  const entries = Object.entries(services)

  return (
    <Card className="h-full">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Activity className="h-4 w-4 text-action" aria-hidden />
          Live resources
        </CardTitle>
      </CardHeader>
      <CardBody className="space-y-2 pt-0">
        {loading && (
          <p className="text-sm text-ink-secondary animate-pulse-soft">Checking services…</p>
        )}
        {error && (
          <div className="space-y-2">
            <p className="text-sm text-status-bad">Could not reach /health/detailed.</p>
            {onRetry && (
              <button
                type="button"
                onClick={onRetry}
                className="text-xs font-medium text-action hover:text-action-hover"
              >
                Retry
              </button>
            )}
          </div>
        )}
        {!loading && !error && entries.length === 0 && (
          <p className="text-sm text-ink-secondary">No service payload yet.</p>
        )}
        {!loading &&
          !error &&
          entries.map(([name, state]) => {
            const tone = normalizeState(state)
            const Icon =
              tone === 'ok' ? CircleCheck : tone === 'bad' ? CircleAlert : Activity
            return (
              <div
                key={name}
                className="flex items-center justify-between gap-3 rounded-md border border-line bg-panel-muted/60 px-3 py-2"
              >
                <div className="flex min-w-0 items-center gap-2">
                  <Icon
                    className={cn(
                      'h-4 w-4 shrink-0',
                      tone === 'ok' && 'text-status-ok',
                      tone === 'bad' && 'text-status-bad',
                      tone === 'warn' && 'text-status-warn',
                      tone === 'unknown' && 'text-ink-subtle',
                    )}
                    aria-hidden
                  />
                  <span className="truncate text-sm font-medium capitalize text-ink">
                    {name.replace(/_/g, ' ')}
                  </span>
                </div>
                <Badge
                  tone={
                    tone === 'ok'
                      ? 'ok'
                      : tone === 'bad'
                        ? 'bad'
                        : tone === 'warn'
                          ? 'warn'
                          : 'neutral'
                  }
                >
                  {state}
                </Badge>
              </div>
            )
          })}
      </CardBody>
    </Card>
  )
}
