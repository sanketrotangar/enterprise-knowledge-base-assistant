import type {
  DocumentPreviewResponse,
  DocumentResponse,
  DocumentRolesResponse,
  DocumentStatusResponse,
  UploadDocumentsResponse,
  UploadOptions,
} from '../types/api'
import { apiFetch } from './client'

/**
 * POST /api/v1/documents/upload — multipart, 1..N files, manager/admin only.
 *
 * Each file becomes an independent document with status `pending`; ingest runs
 * in the worker (Slice 4), so the response returns before any parsing/embedding.
 * No Content-Type header: the browser supplies the multipart boundary.
 */
export async function uploadDocuments(
  files: File[],
  options: UploadOptions,
): Promise<DocumentResponse[]> {
  const form = new FormData()
  for (const file of files) form.append('files', file)
  // The backend applies a title override only to a single file.
  if (options.title && files.length === 1) form.append('title', options.title)
  if (options.roleAccess.length > 0) {
    form.append('role_access', options.roleAccess.join(','))
  }

  const payload = await apiFetch<UploadDocumentsResponse>(
    '/api/v1/documents/upload',
    { method: 'POST', body: form, timeoutMs: 120_000 },
  )
  return payload.documents
}

/** GET /api/v1/documents — RLS-filtered list for the caller's role. */
export function listDocuments(): Promise<DocumentResponse[]> {
  return apiFetch<DocumentResponse[]>('/api/v1/documents', { timeoutMs: 15_000 })
}

/** GET /api/v1/documents/{id}/preview — metadata + text excerpt (404 if hidden). */
export function previewDocument(id: string): Promise<DocumentPreviewResponse> {
  return apiFetch<DocumentPreviewResponse>(
    `/api/v1/documents/${id}/preview`,
    { timeoutMs: 30_000 },
  )
}

/** PUT /api/v1/documents/{id}/roles — manager/admin; chunk re-copy is async. */
export function setDocumentRoles(
  id: string,
  roles: string[],
): Promise<DocumentRolesResponse> {
  return apiFetch<DocumentRolesResponse>(`/api/v1/documents/${id}/roles`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ roles }),
    timeoutMs: 15_000,
  })
}

/** DELETE /api/v1/documents/{id} — manager/admin; hard delete + disk wipe. */
export function deleteDocument(id: string): Promise<void> {
  return apiFetch<void>(`/api/v1/documents/${id}`, {
    method: 'DELETE',
    timeoutMs: 15_000,
  })
}

/** POST /api/v1/documents/{id}/process — re-enqueue ingest by id (async). */
export function processDocument(id: string): Promise<DocumentResponse> {
  return apiFetch<DocumentResponse>(`/api/v1/documents/${id}/process`, {
    method: 'POST',
    timeoutMs: 15_000,
  })
}

/** GET /api/v1/documents/{id}/status — poll while a document is `pending`. */
export function getDocumentStatus(
  id: string,
): Promise<DocumentStatusResponse> {
  return apiFetch<DocumentStatusResponse>(
    `/api/v1/documents/${id}/status`,
    { timeoutMs: 10_000 },
  )
}
