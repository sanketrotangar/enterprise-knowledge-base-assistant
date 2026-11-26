/**
 * Types mirroring the backend API contracts.
 *
 * Sources of truth:
 * - md-files/technical-analysis.md §9 (Task Breakdown) + Appendix A (endpoints)
 * - md-files/document-ingestion-part1.md (Part 1 upload/status contracts)
 * - The router/schema stubs in app/features/*
 *
 * NOTE: search/feedback/admin/auth contracts are defined here so the UI is
 * ready before those backend phases land; only the Part 1 document endpoints
 * exist server-side today.
 */

// --------------------------------------------------------------------------- //
// Shared
// --------------------------------------------------------------------------- //

export type Role = 'user' | 'manager' | 'admin'
export type DocumentStatus = 'pending' | 'ready' | 'failed'
export type SensitivityLevel =
  | 'public'
  | 'internal'
  | 'confidential'
  | 'restricted'

export interface ApiError {
  detail: string | { msg: string; loc?: (string | number)[] }[]
}

// --------------------------------------------------------------------------- //
// Health (implemented in backend Part 1)
// --------------------------------------------------------------------------- //

export interface HealthResponse {
  status: string
  services?: Record<string, string>
}

// --------------------------------------------------------------------------- //
// Documents — Part 1 ingestion (implemented in backend)
// --------------------------------------------------------------------------- //

export interface DocumentResponse {
  id: string
  title: string
  status: DocumentStatus
  chunk_count: number
  file_size_bytes: number | null
  mime_type: string | null
  created_at: string | null
  /** Beta roles allowed to see it (document_role_access). */
  roles: string[]
}

export interface UploadDocumentsResponse {
  documents: DocumentResponse[]
}

export interface DocumentPreviewResponse extends DocumentResponse {
  content: string
  truncated: boolean
  error: string | null
}

export interface DocumentRolesResponse {
  id: string
  roles: string[]
}

export interface DocumentStatusResponse {
  id: string
  status: DocumentStatus
  chunk_count: number
  error: string | null
}

export interface UploadOptions {
  /** Applied only when a single file is uploaded; otherwise filenames are used. */
  title?: string
  /** Empty = legacy default (all beta roles). */
  roleAccess: string[]
}

// --------------------------------------------------------------------------- //
// Auth — Slice 2 (live)
// --------------------------------------------------------------------------- //

export interface AuthUser {
  id: string
  org_id: string
  email: string
  role: Role
}

export interface TokenResponse {
  access_token: string
  token_type: string
  expires_in: number
  user: AuthUser
}

// --------------------------------------------------------------------------- //
// Search — Phase 3 backend (contract defined, not yet implemented)
// --------------------------------------------------------------------------- //

export interface SearchRequest {
  query: string
  top_k: number
  filters?: Record<string, unknown>
}

export interface SearchResult {
  id: string
  document_id: string
  document_title: string
  chunk_index: number
  content: string
  score: number
}

export interface SearchResponse {
  query_id: string
  answer: string
  sources: SearchResult[]
  response_time_ms: number
}

export interface SearchHistoryItem {
  id: string
  query_text: string
  created_at: string
  results_count: number
}

// --------------------------------------------------------------------------- //
// Feedback — Phase 4 backend (contract defined, not yet implemented)
// --------------------------------------------------------------------------- //

export type FeedbackRating = 'useful' | 'not_useful' | 'partial'

export interface FeedbackRequest {
  query_id: string
  rating: FeedbackRating
  comment?: string
}

export interface FeedbackResponse {
  id: string
  rating: FeedbackRating
  created_at: string
}

export interface FeedbackSummary {
  total_useful: number
  total_not_useful: number
  total_partial: number
  total: number
  percentage_useful: number
}

// --------------------------------------------------------------------------- //
// Admin — Phase 5 backend (contract defined, not yet implemented)
// --------------------------------------------------------------------------- //

export interface AdminDocument {
  id: string
  title: string
  status: DocumentStatus
  sensitivity: SensitivityLevel
  source_type: string
  file_size_bytes: number | null
  chunk_count: number
  uploaded_by_email?: string | null
  created_at: string | null
}

export interface AdminUser {
  id: string
  name: string
  email: string
  role: 'admin' | 'manager' | 'employee' | 'intern'
  department: string | null
  is_active: boolean
  created_at: string | null
}

export interface AuditLogEntry {
  id: string
  action: string
  resource_type: string | null
  resource_id: string | null
  user_email?: string | null
  details?: Record<string, unknown>
  created_at: string
}

export interface RoleUpdateRequest {
  role: AdminUser['role']
}
