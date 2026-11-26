import { Badge } from '../ui/badge'
import { STATUS_STYLES } from '../../lib/statusMeta'
import type { DocumentStatus } from '../../types/api'

interface StatusBadgeProps {
  status: DocumentStatus | string
}

/** Status badge: color + label always paired (never color alone). */
export function StatusBadge({ status }: StatusBadgeProps) {
  const meta = STATUS_STYLES[status as DocumentStatus] ?? STATUS_STYLES.pending
  return (
    <Badge className={meta.badgeClass}>
      <span className={`h-1.5 w-1.5 rounded-full ${meta.dotClass}`} aria-hidden="true" />
      {meta.label}
    </Badge>
  )
}
