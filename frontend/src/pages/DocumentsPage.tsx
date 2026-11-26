import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  deleteDocument,
  listDocuments,
  processDocument,
} from '../api/documents'
import { DocumentIcon, ArrowUpTrayIcon } from '../components/icons'
import { PreviewModal } from '../components/documents/PreviewModal'
import { RolesModal } from '../components/documents/RolesModal'
import { StatusBadge } from '../components/documents/StatusBadge'
import { UploadModal } from '../components/documents/UploadModal'
import { Badge } from '../components/ui/badge'
import { Button } from '../components/ui/button'
import { Card, CardBody } from '../components/ui/card'
import { Modal } from '../components/ui/Modal'
import { EmptyState, ErrorState } from '../components/ui/states'
import { useAuth } from '../features/auth/AuthProvider'
import { usePageTitle } from '../features/usePageTitle'
import { formatBytes, formatDateTime } from '../lib/format'
import type { DocumentResponse } from '../types/api'

/**
 * Documents page (Slice 3 surface, Slice 6 UI).
 *
 * - Every caller sees the RLS-filtered list (role decides visibility in the DB)
 * - manager/admin additionally upload, delete, retry and edit role access
 * - Pending documents poll every 3s; ingest itself runs in the Slice 4 worker
 * - Upload closes as soon as the API accepts the files (never waits on embed)
 */
export function DocumentsPage() {
  const { setTitle } = usePageTitle('')
  useEffect(() => setTitle('Documents'), [setTitle])

  const { user } = useAuth()
  const canManage = user?.role === 'manager' || user?.role === 'admin'
  const queryClient = useQueryClient()

  const docs = useQuery({
    queryKey: ['documents'],
    queryFn: listDocuments,
    retry: false,
    refetchInterval: (query) =>
      query.state.data?.some((doc) => doc.status === 'pending') ? 3_000 : false,
  })

  const [uploadOpen, setUploadOpen] = useState(false)
  const [previewDoc, setPreviewDoc] = useState<DocumentResponse | null>(null)
  const [rolesDoc, setRolesDoc] = useState<DocumentResponse | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<DocumentResponse | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)

  const remove = useMutation({
    mutationFn: (id: string) => deleteDocument(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['documents'] })
      setDeleteTarget(null)
      setActionError(null)
    },
    onError: (error: Error) => setActionError(error.message),
  })

  const reprocess = useMutation({
    mutationFn: (id: string) => processDocument(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['documents'] })
      setActionError(null)
    },
    onError: (error: Error) => setActionError(error.message),
  })

  const documents = docs.data ?? []
  const pending = documents.filter((doc) => doc.status === 'pending').length

  return (
    <div className="mx-auto max-w-6xl space-y-6 p-4 sm:p-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h2 className="text-lg font-semibold text-ink">Documents</h2>
          <p className="mt-0.5 text-sm text-ink-secondary">
            {canManage
              ? 'Upload files and manage who can see them. Ingestion runs in the background.'
              : 'Documents your role can access. Access is enforced by the database.'}
          </p>
        </div>
        {canManage && (
          <Button onClick={() => setUploadOpen(true)}>
            <ArrowUpTrayIcon className="h-4 w-4" />
            Upload documents
          </Button>
        )}
      </div>

      {actionError && (
        <p
          role="alert"
          className="rounded-md border border-status-bad/30 bg-status-bad-soft px-3 py-2 text-sm text-status-bad"
        >
          {actionError}
        </p>
      )}

      {docs.isError && (
        <Card>
          <CardBody>
            <ErrorState
              message={
                docs.error instanceof Error
                  ? docs.error.message
                  : 'Could not load the document list.'
              }
              onRetry={() => docs.refetch()}
            />
          </CardBody>
        </Card>
      )}

      {docs.isLoading && (
        <Card>
          <CardBody className="space-y-3" aria-busy="true">
            {[0, 1, 2].map((row) => (
              <div key={row} className="h-14 animate-pulse rounded bg-subtle" />
            ))}
          </CardBody>
        </Card>
      )}

      {docs.isSuccess && documents.length === 0 && (
        <Card>
          <CardBody>
            <EmptyState
              title="No documents yet"
              message={
                canManage
                  ? 'Upload a PDF, TXT or Markdown file. It is accepted immediately and ingested in the background.'
                  : 'Nothing has been shared with your role yet. Ask a manager or admin to upload a document for you.'
              }
              action={
                canManage ? (
                  <Button
                    variant="secondary"
                    onClick={() => setUploadOpen(true)}
                  >
                    <ArrowUpTrayIcon className="h-4 w-4" />
                    Choose files
                  </Button>
                ) : undefined
              }
            />
          </CardBody>
        </Card>
      )}

      {docs.isSuccess && documents.length > 0 && (
        <Card>
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-4 py-3">
            <div className="flex items-center gap-2">
              <DocumentIcon className="h-4 w-4 text-action" aria-hidden />
              <h3 className="text-sm font-semibold text-ink">
                {documents.length} document{documents.length === 1 ? '' : 's'}
              </h3>
              {pending > 0 && (
                <Badge tone="warn">
                  {pending} pending ingest
                </Badge>
              )}
            </div>
            <Button variant="ghost" size="sm" onClick={() => docs.refetch()}>
              Refresh
            </Button>
          </div>

          <ul role="list" className="divide-y divide-line">
            {documents.map((doc) => (
              <li
                key={doc.id}
                className="flex flex-col gap-3 px-4 py-3 sm:flex-row sm:items-center"
              >
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium text-ink">
                    {doc.title}
                  </p>
                  <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-ink-secondary">
                    <StatusBadge status={doc.status} />
                    <span>{doc.chunk_count} chunks</span>
                    <span aria-hidden>·</span>
                    <span>{formatBytes(doc.file_size_bytes)}</span>
                    <span aria-hidden>·</span>
                    <span>{formatDateTime(doc.created_at)}</span>
                  </div>
                  <div className="mt-1.5 flex flex-wrap items-center gap-1">
                    <span className="text-[11px] uppercase tracking-wide text-ink-subtle">
                      Roles
                    </span>
                    {doc.roles.length === 0 ? (
                      <Badge tone="warn">manager / admin</Badge>
                    ) : (
                      doc.roles.map((role) => (
                        <Badge
                          key={role}
                          tone="neutral"
                          className="capitalize"
                        >
                          {role}
                        </Badge>
                      ))
                    )}
                  </div>
                </div>

                <div className="flex shrink-0 flex-wrap items-center gap-1">
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => setPreviewDoc(doc)}
                  >
                    Preview
                  </Button>
                  {canManage && (
                    <>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => setRolesDoc(doc)}
                      >
                        Roles
                      </Button>
                      {doc.status === 'failed' && (
                        <Button
                          variant="ghost"
                          size="sm"
                          loading={
                            reprocess.isPending &&
                            reprocess.variables === doc.id
                          }
                          onClick={() => reprocess.mutate(doc.id)}
                        >
                          Retry ingest
                        </Button>
                      )}
                      <Button
                        variant="ghost"
                        size="sm"
                        className="text-status-bad hover:text-status-bad"
                        onClick={() => setDeleteTarget(doc)}
                      >
                        Delete
                      </Button>
                    </>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </Card>
      )}

      <p className="text-xs text-ink-subtle">
        Pending documents refresh automatically. Deleting a document removes the
        stored file, its chunks and its role rows.
      </p>

      {canManage && (
        <UploadModal
          open={uploadOpen}
          onClose={() => setUploadOpen(false)}
          onUploaded={() => {
            queryClient.invalidateQueries({ queryKey: ['documents'] })
          }}
        />
      )}

      <PreviewModal
        doc={previewDoc}
        open={Boolean(previewDoc)}
        onClose={() => setPreviewDoc(null)}
      />

      <RolesModal
        doc={rolesDoc}
        open={Boolean(rolesDoc)}
        onClose={() => setRolesDoc(null)}
      />

      <Modal
        open={Boolean(deleteTarget)}
        onClose={() => {
          if (!remove.isPending) setDeleteTarget(null)
        }}
        title="Delete document"
      >
        <div className="space-y-4">
          <p className="text-sm text-ink-secondary">
            Permanently delete{' '}
            <strong className="text-ink">{deleteTarget?.title}</strong>? The
            stored file, chunks and role rows are removed. This cannot be
            undone.
          </p>
          {remove.isError && (
            <p
              role="alert"
              className="rounded-md border border-status-bad/30 bg-status-bad-soft px-3 py-2 text-sm text-status-bad"
            >
              {remove.error instanceof Error
                ? remove.error.message
                : 'Delete failed.'}
            </p>
          )}
          <div className="flex justify-end gap-2 border-t border-line pt-4">
            <Button
              variant="secondary"
              onClick={() => setDeleteTarget(null)}
              disabled={remove.isPending}
            >
              Cancel
            </Button>
            <Button
              variant="danger"
              loading={remove.isPending}
              onClick={() => {
                if (deleteTarget) remove.mutate(deleteTarget.id)
              }}
            >
              Delete
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  )
}
