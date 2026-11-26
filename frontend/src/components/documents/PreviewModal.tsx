import { useQuery } from '@tanstack/react-query'

import { previewDocument } from '../../api/documents'
import { formatBytes, formatDateTime } from '../../lib/format'
import type { DocumentResponse } from '../../types/api'
import { Badge } from '../ui/badge'
import { Modal } from '../ui/Modal'
import { ErrorState } from '../ui/states'
import { StatusBadge } from './StatusBadge'

/**
 * Read-only preview: metadata + the first 5000 chars of the stored file.
 * The endpoint 404s for documents the caller's role cannot see — the UI never
 * receives hidden documents in the first place (list is RLS-filtered).
 */
export function PreviewModal({
  doc,
  open,
  onClose,
}: {
  doc: DocumentResponse | null
  open: boolean
  onClose: () => void
}) {
  const query = useQuery({
    queryKey: ['document-preview', doc?.id],
    enabled: open && Boolean(doc),
    retry: false,
    queryFn: () => previewDocument(doc!.id),
  })

  return (
    <Modal open={open} onClose={onClose} title={doc?.title ?? 'Preview'} wide>
      {query.isLoading && (
        <div className="space-y-2" aria-busy="true">
          <div className="h-3 w-1/3 animate-pulse rounded bg-subtle" />
          <div className="h-32 animate-pulse rounded bg-subtle" />
        </div>
      )}

      {query.isError && (
        <ErrorState
          message={
            query.error instanceof Error
              ? query.error.message
              : 'Could not load this preview.'
          }
          onRetry={() => query.refetch()}
        />
      )}

      {query.data && (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge status={query.data.status} />
            <Badge tone="neutral">{query.data.chunk_count} chunks</Badge>
            <Badge tone="neutral">
              {formatBytes(query.data.file_size_bytes)}
            </Badge>
            <span className="text-xs text-ink-secondary">
              {formatDateTime(query.data.created_at)}
            </span>
          </div>

          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-xs font-medium text-ink-secondary">
              Visible to:
            </span>
            {query.data.roles.length === 0 ? (
              <Badge tone="warn">manager / admin only</Badge>
            ) : (
              query.data.roles.map((role) => (
                <Badge key={role} tone="action" className="capitalize">
                  {role}
                </Badge>
              ))
            )}
          </div>

          {query.data.status === 'failed' && (
            <p
              role="alert"
              className="rounded-md border border-status-bad/30 bg-status-bad-soft px-3 py-2 text-sm text-status-bad"
            >
              {query.data.error ?? 'Ingestion failed for this document.'}
            </p>
          )}

          <div>
            <p className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-ink-subtle">
              Content{query.data.truncated ? ' (truncated)' : ''}
            </p>
            <pre className="max-h-80 overflow-auto whitespace-pre-wrap rounded-md border border-line bg-panel-muted p-3 font-mono text-xs leading-relaxed text-ink">
              {query.data.content || 'No extracted text available.'}
            </pre>
          </div>
        </div>
      )}
    </Modal>
  )
}
