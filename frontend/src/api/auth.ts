import type { TokenResponse } from '../types/api'
import { apiFetch } from './client'

/**
 * POST /api/v1/auth/login — email + password -> JWT (org_id, user_id, role).
 * `orgId` is only needed when the same email exists in more than one org.
 */
export function login(
  email: string,
  password: string,
  orgId?: string,
): Promise<TokenResponse> {
  return apiFetch<TokenResponse>('/api/v1/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      email,
      password,
      ...(orgId ? { org_id: orgId } : {}),
    }),
    timeoutMs: 15_000,
    skipAuth: true,
  })
}
