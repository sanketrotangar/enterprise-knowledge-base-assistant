import type { AuthUser } from '../types/api'

/**
 * Client session: the JWT + the identity the API returned with it.
 *
 * Kept in localStorage so a refresh does not log the user out. The token is
 * the only credential the frontend holds; every API route re-derives org/role
 * server-side and Postgres RLS enforces access.
 */
export interface Session {
  token: string
  user: AuthUser
}

const STORAGE_KEY = 'ka.session'

/** Fired when the API answers 401 so the provider can drop the session. */
export const SESSION_EXPIRED_EVENT = 'ka:session-expired'

export function readSession(): Session | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as Partial<Session> | null
    if (!parsed?.token || !parsed.user?.email || !parsed.user.role) return null
    return { token: parsed.token, user: parsed.user }
  } catch {
    return null
  }
}

export function saveSession(session: Session): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(session))
}

export function clearSession(): void {
  localStorage.removeItem(STORAGE_KEY)
}

export function getToken(): string | null {
  return readSession()?.token ?? null
}

export function notifySessionExpired(): void {
  window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT))
}
