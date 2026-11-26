import { Link } from 'react-router-dom'
import { FileText } from 'lucide-react'
import { Card, CardBody, CardHeader, CardTitle } from '@/components/ui/card'
import { StatusBadge } from '@/components/documents/StatusBadge'
import { formatRelativeTime } from '@/lib/format'

export interface ActivityItem {
  id: string
  title: string
  status: string
  created_at: string | null
}

export function RecentActivity({
  items,
  emptyHint = 'No recent activity yet. Uploads and asks will show up here.',
}: {
  items: ActivityItem[]
  emptyHint?: string
}) {
  return (
    <Card className="h-full">
      <CardHeader>
        <CardTitle>Recent activity</CardTitle>
        <Link
          to="/documents"
          className="text-xs font-semibold text-action hover:text-action-hover"
        >
          Documents
        </Link>
      </CardHeader>
      <CardBody className="pt-0">
        {items.length === 0 ? (
          <p className="py-8 text-center text-sm text-ink-secondary">{emptyHint}</p>
        ) : (
          <ul role="list" className="divide-y divide-line">
            {items.map((item) => (
              <li key={item.id} className="flex items-center gap-3 py-2.5">
                <span className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-panel-muted text-ink-secondary">
                  <FileText className="h-4 w-4" aria-hidden />
                </span>
                <span className="min-w-0 flex-1 truncate text-sm font-medium text-ink">
                  {item.title}
                </span>
                <StatusBadge status={item.status} />
                <span className="hidden w-20 text-right text-xs text-ink-subtle sm:block">
                  {formatRelativeTime(item.created_at)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </CardBody>
    </Card>
  )
}
