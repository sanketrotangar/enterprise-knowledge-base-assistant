import type { HealthResponse } from '../types/api'
import { apiFetch } from './client'

/** GET /health — basic liveness (used for the sidebar status dot). */
export function getHealth(): Promise<HealthResponse> {
  return apiFetch<HealthResponse>('/health', { timeoutMs: 5_000 })
}

/** GET /health/detailed — per-service status for the dashboard cards. */
export function getDetailedHealth(): Promise<HealthResponse> {
  return apiFetch<HealthResponse>('/health/detailed', { timeoutMs: 5_000 })
}
