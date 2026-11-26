import { API_BASE_URL } from '../lib/env'
import { clearSession, getToken, notifySessionExpired } from '../lib/session'
import type { ApiError } from '../types/api'

/** Shape of a failed API call surfaced to the UI. */
export class ApiClientError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiClientError'
    this.status = status
  }
}

/** Build the request URL (empty API_BASE_URL = same-origin via Vite proxy). */
export function buildUrl(path: string): string {
  return `${API_BASE_URL}${path}`
}

interface ApiFetchOptions extends RequestInit {
  timeoutMs?: number
  /** Login is the one call that must not rely on (or clear) a session. */
  skipAuth?: boolean
}

/**
 * Thin fetch wrapper around the FastAPI backend.
 * - Attaches the Bearer token from the stored session
 * - A 401 clears the session and notifies the auth provider (redirect to login)
 * - Parses FastAPI's error envelope ({detail: ...}) into a readable message
 * - Supports optional request timeouts
 */
export async function apiFetch<T>(
  path: string,
  options: ApiFetchOptions = {},
): Promise<T> {
  const { timeoutMs, skipAuth = false, ...fetchOptions } = options

  const headers = new Headers(fetchOptions.headers)
  if (!skipAuth) {
    const token = getToken()
    if (token) headers.set('Authorization', `Bearer ${token}`)
  }

  const controller = new AbortController()
  const timer =
    timeoutMs !== undefined
      ? setTimeout(() => controller.abort(), timeoutMs)
      : undefined

  try {
    const response = await fetch(buildUrl(path), {
      ...fetchOptions,
      headers,
      signal: controller.signal,
    })
    if (response.status === 401 && !skipAuth) {
      clearSession()
      notifySessionExpired()
    }
    if (!response.ok) {
      throw new ApiClientError(response.status, await extractError(response))
    }
    if (response.status === 204) return undefined as T
    return (await response.json()) as T
  } finally {
    if (timer) clearTimeout(timer)
  }
}

async function extractError(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as ApiError
    if (typeof body.detail === 'string') return body.detail
    if (Array.isArray(body.detail)) {
      // FastAPI validation errors: [{msg, loc}, ...]
      return body.detail.map((d) => d.msg).join('; ')
    }
  } catch {
    // fall through — non-JSON error body
  }
  return `Request failed (${response.status})`
}
