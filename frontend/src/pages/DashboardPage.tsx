import { useEffect } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  Boxes,
  Database,
  FileStack,
  Layers3,
  Timer,
  Upload,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { BentoCell, BentoGrid } from '@/components/dashboard/BentoGrid'
import { MetricTile } from '@/components/dashboard/MetricTile'
import { ServiceStatusTile } from '@/components/dashboard/ServiceStatusTile'
import { RecentActivity } from '@/components/dashboard/RecentActivity'
import { AnalyticsStrip } from '@/components/dashboard/AnalyticsStrip'
import { useDetailedHealth } from '@/features/useSystemHealth'
import { usePageTitle } from '@/features/usePageTitle'
import { listDocuments } from '@/api/documents'

/**
 * Ops dashboard (bento). Wire live counts when list/metrics APIs exist;
 * unavailable values render as "—".
 */
export function DashboardPage() {
  const { setTitle } = usePageTitle('')
  useEffect(() => {
    setTitle('Dashboard')
  }, [setTitle])

  const detailed = useDetailedHealth()
  const docs = useQuery({
    queryKey: ['documents'],
    queryFn: listDocuments,
    retry: false,
  })

  const services = detailed.data?.services ?? {}
  const docList = docs.data ?? []
  const docsAvailable = docs.isSuccess
  const ready = docsAvailable
    ? docList.filter((d) => d.status === 'ready').length
    : null
  const processing = docsAvailable
    ? docList.filter((d) => d.status === 'pending').length
    : null
  const failed = docsAvailable
    ? docList.filter((d) => d.status === 'failed').length
    : null
  const totalDocs = docsAvailable ? docList.length : null
  const totalChunks = docsAvailable
    ? docList.reduce((sum, d) => sum + (d.chunk_count || 0), 0)
    : null
  const recent = docsAvailable
    ? [...docList]
        .sort((a, b) => (b.created_at ?? '').localeCompare(a.created_at ?? ''))
        .slice(0, 6)
    : []

  // Frozen eval snapshot values — live wiring later (slice 7 / metrics API).
  const evalSnapshot = {
    hitAt1: '17/18',
    mrr: '0.972',
    leakRate: '0/30',
    p95Ms: '419ms',
  }

  return (
    <div className="mx-auto max-w-7xl space-y-6 p-4 sm:p-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h2 className="text-xl font-semibold tracking-tight text-ink">
            Operations dashboard
          </h2>
          <p className="mt-1 max-w-xl text-sm text-ink-secondary">
            Corpus health, live stack resources, and retrieval quality signals
            for Knowledge Assistant.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button asChild variant="secondary" size="sm">
            <Link to="/search">Ask</Link>
          </Button>
          <Button asChild size="sm">
            <Link to="/documents">
              <Upload className="h-4 w-4" />
              Documents
            </Link>
          </Button>
        </div>
      </div>

      <BentoGrid>
        <BentoCell>
          <MetricTile
            label="Documents"
            value={totalDocs}
            hint={docs.isError ? 'List unavailable' : 'Visible to your role'}
            icon={FileStack}
            accent="docs"
          />
        </BentoCell>
        <BentoCell>
          <MetricTile
            label="Chunks / embeddings"
            value={totalChunks}
            hint="Indexed text units"
            icon={Layers3}
            accent="chunks"
          />
        </BentoCell>
        <BentoCell>
          <MetricTile
            label="Ready"
            value={ready}
            hint="Status = ready"
            icon={Database}
            accent="docs"
          />
        </BentoCell>
        <BentoCell>
          <MetricTile
            label="In queue / failed"
            value={
              processing === null || failed === null
                ? null
                : `${processing} / ${failed}`
            }
            hint="Pending processing vs failed"
            icon={Boxes}
            accent="queue"
          />
        </BentoCell>

        <BentoCell className="sm:col-span-2 xl:col-span-2 xl:row-span-2">
          <ServiceStatusTile
            services={services}
            loading={detailed.isLoading}
            error={detailed.isError}
            onRetry={() => detailed.refetch()}
          />
        </BentoCell>

        <BentoCell className="sm:col-span-2 xl:col-span-2">
          <AnalyticsStrip
            hitAt1={evalSnapshot.hitAt1}
            mrr={evalSnapshot.mrr}
            leakRate={evalSnapshot.leakRate}
            p95Ms={evalSnapshot.p95Ms}
          />
        </BentoCell>

        <BentoCell>
          <MetricTile
            label="Ask p95 (live)"
            value={null}
            hint="Needs metrics endpoint"
            icon={Timer}
            accent="latency"
          />
        </BentoCell>
        <BentoCell>
          <MetricTile
            label="Role-sync jobs"
            value={null}
            hint="Worker queue depth"
            icon={Boxes}
            accent="queue"
          />
        </BentoCell>

        <BentoCell className="sm:col-span-2 xl:col-span-4">
          <RecentActivity
            items={recent}
            emptyHint={
              docs.isError
                ? 'Document list unavailable — check the API and sign-in.'
                : 'No documents yet. Upload from Documents to populate activity.'
            }
          />
        </BentoCell>
      </BentoGrid>
    </div>
  )
}
