import { useEffect } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { getDocumentStatus, processDocument } from '../../api/documents'
import { StatusBadge } from './StatusBadge'
import { Button } from '../ui/button'
import { ArrowPathIcon } from '../icons'

interface DocumentStatusPollerProps {
  /** Document to poll. When omitted, shows nothing (initial state). */
  docId: string | null
  /** Called when processing reaches a terminal state. */
  onSettled?: (status: string) => void
}

/**
 * Polls GET /documents/{id}/status every 2s while the document is in a
 * non-terminal state, then stops automatically. Offers "Reprocess" for
 * failed documents via POST /documents/{id}/process.
 */
export function DocumentStatusPoller({ docId, onSettled }: DocumentStatusPollerProps) {
  const queryClient = useQueryClient()
  const active = Boolean(docId)

  const statusQuery = useQuery({
    queryKey: ['document-status', docId],
    enabled: active,
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status === 'pending' ? 2_000 : false
    },
    retry: false,
    queryFn: () => {
      if (!docId) return Promise.reject(new Error('No document selected'))
      return getDocumentStatus(docId)
    },
  })

  const reprocess = useMutation({
    mutationFn: () => {
      if (!docId) return Promise.reject(new Error('No document selected'))
      return processDocument(docId)
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['document-status', docId] }),
  })

  const status = statusQuery.data?.status

  useEffect(() => {
    if (status === 'ready' || status === 'failed') onSettled?.(status)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status])

  if (!docId) return null

  return (
    <div
      role="status"
      className="flex flex-wrap items-center gap-3 rounded-lg border border-default bg-surface p-4"
    >
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-fg">
          Ingestion pipeline
          <span className="ml-2 font-mono text-xs text-muted">{shortId(docId)}</span>
        </p>
        <div className="mt-1.5 flex flex-wrap items-center gap-2 text-sm">
          {statusQuery.isLoading ? (
            <span className="text-muted">Checking status…</span>
          ) : statusQuery.isError ? (
            <span className="text-danger-text">Status check failed — is the API running?</span>
          ) : (
            <>
              <StatusBadge status={status ?? 'pending'} />
              {status === 'ready' && (
                <span className="text-muted">
                  {statusQuery.data?.chunk_count} chunks ready
                </span>
              )}
              {status === 'failed' && statusQuery.data?.error && (
                <span className="truncate text-danger-text" title={statusQuery.data.error}>
                  {statusQuery.data.error}
                </span>
              )}
              {status === 'pending' && (
                <span className="text-muted">Parsing → chunking → embedding…</span>
              )}
            </>
          )}
        </div>
      </div>

      {(status === 'failed' || status === 'ready') && (
        <Button
          variant="secondary"
          size="sm"
          loading={reprocess.isPending}
          onClick={() => reprocess.mutate()}
        >
          <ArrowPathIcon className="h-4 w-4" />
          Reprocess
        </Button>
      )}
    </div>
  )
}

function shortId(id: string): string {
  return id.length > 12 ? `${id.slice(0, 8)}…` : id
}
