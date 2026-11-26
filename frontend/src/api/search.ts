import type { SearchRequest, SearchResponse } from '../types/api'
import { apiFetch } from './client'

/** POST /api/v1/search — ask + sources in the response (no history). */
export function search(request: SearchRequest): Promise<SearchResponse> {
  return apiFetch<SearchResponse>('/api/v1/search', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
    timeoutMs: 60_000,
  })
}
