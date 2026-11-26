import { useRef, useState } from 'react'
import { useMutation } from '@tanstack/react-query'

import { uploadDocuments } from '../../api/documents'
import { titleFromFilename } from '../../lib/format'
import type { DocumentResponse, Role, UploadOptions } from '../../types/api'
import { Button } from '../ui/button'
import { Field, TextInput } from '../ui/Field'
import { DocumentIcon } from '../icons'
import { Modal } from '../ui/Modal'

const BETA_ROLES: Role[] = ['user', 'manager', 'admin']
const MAX_FILES = 10
const MAX_BYTES = 50 * 1024 * 1024
const ALLOWED_EXTENSIONS = ['.pdf', '.txt', '.md']

interface UploadModalProps {
  open: boolean
  onClose: () => void
  /** Receives the accepted documents (each is an independent pending job). */
  onUploaded: (documents: DocumentResponse[]) => void
}

/**
 * Upload dialog: 1..N files + title + role access → POST /documents/upload.
 *
 * The API accepts the files, writes them to disk, creates `pending` rows and
 * enqueues one ingest job per document. Ingest runs in the worker, so this
 * dialog closes as soon as the upload is accepted.
 */
export function UploadModal({ open, onClose, onUploaded }: UploadModalProps) {
  const [files, setFiles] = useState<File[]>([])
  const [title, setTitle] = useState('')
  const [roles, setRoles] = useState<string[]>([])
  const [error, setError] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  const upload = useMutation({
    mutationFn: (options: UploadOptions) => uploadDocuments(files, options),
    onSuccess: (documents) => {
      reset()
      onUploaded(documents)
      onClose()
    },
    onError: (err: Error) => setError(err.message),
  })

  function reset() {
    setFiles([])
    setTitle('')
    setRoles([])
    setError(null)
    if (inputRef.current) inputRef.current.value = ''
  }

  function onFilesPicked(picked: FileList | null) {
    setError(null)
    if (!picked || picked.length === 0) return

    const next = [...picked]
    if (next.length > MAX_FILES) {
      setError(`Select at most ${MAX_FILES} files at a time.`)
      return
    }

    for (const file of next) {
      const extension = `.${file.name.split('.').pop()?.toLowerCase() ?? ''}`
      if (!ALLOWED_EXTENSIONS.includes(extension)) {
        setError(`Unsupported file type "${extension}". Allowed: PDF, TXT, Markdown.`)
        return
      }
      if (file.size === 0) {
        setError(`"${file.name}" is empty.`)
        return
      }
      if (file.size > MAX_BYTES) {
        setError(`"${file.name}" exceeds the 50 MB limit.`)
        return
      }
    }

    setFiles(next)
    if (next.length === 1) setTitle(titleFromFilename(next[0].name))
  }

  function toggleRole(role: Role) {
    setRoles((current) =>
      current.includes(role)
        ? current.filter((item) => item !== role)
        : [...current, role],
    )
  }

  function submit(event: React.FormEvent) {
    event.preventDefault()
    if (files.length === 0) {
      setError('Choose at least one file to upload.')
      return
    }
    setError(null)
    upload.mutate({ title: title.trim() || undefined, roleAccess: roles })
  }

  function close() {
    if (upload.isPending) return
    reset()
    onClose()
  }

  const totalBytes = files.reduce((sum, file) => sum + file.size, 0)

  return (
    <Modal open={open} onClose={close} title="Upload documents" wide>
      <form onSubmit={submit} className="space-y-4">
        <div>
          <input
            ref={inputRef}
            id="file-input"
            type="file"
            multiple
            accept=".pdf,.txt,.md,application/pdf,text/plain,text/markdown"
            className="sr-only"
            onChange={(event) => onFilesPicked(event.target.files)}
          />
          <button
            type="button"
            onClick={() => inputRef.current?.click()}
            aria-describedby={error ? 'upload-error' : undefined}
            className="flex w-full flex-col items-center rounded-lg border-2 border-dashed border-strong bg-subtle px-4 py-7 text-center transition-colors hover:border-brand hover:bg-brand-light/20"
          >
            <DocumentIcon className="h-8 w-8 text-muted" />
            {files.length === 0 ? (
              <>
                <span className="mt-2 text-sm font-medium text-fg">
                  Click to choose files
                </span>
                <span className="mt-0.5 text-xs text-muted">
                  PDF, TXT or Markdown — up to {MAX_FILES} files, 50 MB each
                </span>
              </>
            ) : (
              <>
                <span className="mt-2 text-sm font-medium text-fg">
                  {files.length} file{files.length === 1 ? '' : 's'} selected
                </span>
                <span className="mt-0.5 text-xs text-muted">
                  {formatSize(totalBytes)} total — click to replace
                </span>
              </>
            )}
          </button>
          {files.length > 0 && (
            <ul className="mt-2 space-y-1">
              {files.map((file) => (
                <li
                  key={`${file.name}-${file.size}`}
                  className="flex items-center justify-between gap-2 rounded-md bg-panel-muted px-2.5 py-1.5 text-xs"
                >
                  <span className="truncate text-ink">{file.name}</span>
                  <span className="shrink-0 text-ink-subtle">
                    {formatSize(file.size)}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>

        <Field
          label="Title"
          htmlFor="doc-title"
          hint={
            files.length > 1
              ? 'Multiple files keep their own filenames as titles.'
              : 'Defaults to the filename. Used as the citation label in Ask.'
          }
        >
          <TextInput
            id="doc-title"
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            placeholder="e.g. Leave Policy"
            maxLength={500}
            disabled={files.length > 1}
          />
        </Field>

        <fieldset>
          <legend className="mb-1.5 block text-sm font-medium text-fg">
            Who can see this (roles)
          </legend>
          <div className="flex flex-wrap gap-2">
            {BETA_ROLES.map((role) => (
              <label
                key={role}
                className={`inline-flex cursor-pointer items-center gap-2 rounded-full border px-3 py-1.5 text-sm capitalize transition-colors ${
                  roles.includes(role)
                    ? 'border-brand bg-brand-light/40 text-brand-dark'
                    : 'border-default bg-surface text-muted hover:bg-subtle'
                }`}
              >
                <input
                  type="checkbox"
                  className="sr-only"
                  checked={roles.includes(role)}
                  onChange={() => toggleRole(role)}
                />
                {role}
              </label>
            ))}
          </div>
          <p className="mt-1.5 text-xs text-muted">
            Leave empty to allow user, manager and admin.
          </p>
        </fieldset>

        <p className="rounded-md border border-line bg-panel-muted px-3 py-2 text-xs text-ink-secondary">
          Parsing, chunking and embedding run in the background. Uploads return
          immediately with status <strong>pending</strong>.
        </p>

        {error && (
          <p
            id="upload-error"
            role="alert"
            className="rounded-md border border-status-bad/30 bg-status-bad-soft px-3 py-2 text-sm text-status-bad"
          >
            {error}
          </p>
        )}

        <div className="flex justify-end gap-2 border-t border-default pt-4">
          <Button type="button" variant="secondary" onClick={close}>
            Cancel
          </Button>
          <Button type="submit" loading={upload.isPending}>
            {upload.isPending
              ? 'Uploading…'
              : `Upload ${files.length || ''} file${files.length === 1 ? '' : 's'}`.trim()}
          </Button>
        </div>
      </form>
    </Modal>
  )
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}
