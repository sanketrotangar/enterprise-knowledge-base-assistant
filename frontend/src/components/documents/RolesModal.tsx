import { useEffect, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'

import { setDocumentRoles } from '../../api/documents'
import type { DocumentResponse, Role } from '../../types/api'
import { Button } from '../ui/button'
import { Modal } from '../ui/Modal'

const ROLES: Role[] = ['user', 'manager', 'admin']

/**
 * Edit document_role_access (manager/admin only).
 *
 * The API updates the document rows immediately and enqueues a worker job that
 * re-copies the roles onto chunks, so retrieval changes are eventually
 * consistent — no blocking spinner here.
 */
export function RolesModal({
  doc,
  open,
  onClose,
}: {
  doc: DocumentResponse | null
  open: boolean
  onClose: () => void
}) {
  const queryClient = useQueryClient()
  const [roles, setRoles] = useState<string[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (open) {
      setRoles(doc?.roles ?? [])
      setError(null)
    }
  }, [open, doc])

  const save = useMutation({
    mutationFn: () => setDocumentRoles(doc!.id, roles),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['documents'] })
      queryClient.invalidateQueries({ queryKey: ['document-preview', doc?.id] })
      onClose()
    },
    onError: (err: Error) => setError(err.message),
  })

  function toggle(role: Role) {
    setRoles((current) =>
      current.includes(role)
        ? current.filter((item) => item !== role)
        : [...current, role],
    )
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={`Roles — ${doc?.title ?? 'document'}`}
    >
      <div className="space-y-4">
        <p className="text-sm text-ink-secondary">
          Choose which beta roles can list, preview and retrieve this document.
        </p>

        <fieldset className="space-y-1.5">
          <legend className="sr-only">Visible roles</legend>
          {ROLES.map((role) => (
            <label
              key={role}
              className="flex cursor-pointer items-center gap-3 rounded-md border border-line bg-panel-muted px-3 py-2.5 text-sm capitalize text-ink hover:bg-panel"
            >
              <input
                type="checkbox"
                className="h-4 w-4 rounded border-line text-action focus:ring-action"
                checked={roles.includes(role)}
                onChange={() => toggle(role)}
              />
              {role}
            </label>
          ))}
        </fieldset>

        <p className="text-xs text-ink-subtle">
          No roles selected = manager/admin only. Chunk access is re-synced by
          the background worker, so retrieval catches up without blocking this
          request.
        </p>

        {error && (
          <p
            role="alert"
            className="rounded-md border border-status-bad/30 bg-status-bad-soft px-3 py-2 text-sm text-status-bad"
          >
            {error}
          </p>
        )}

        <div className="flex justify-end gap-2 border-t border-line pt-4">
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button loading={save.isPending} onClick={() => save.mutate()}>
            Save roles
          </Button>
        </div>
      </div>
    </Modal>
  )
}
