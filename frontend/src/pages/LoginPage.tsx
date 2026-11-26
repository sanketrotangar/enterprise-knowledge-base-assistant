import { useEffect, useState } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'

import { Button } from '../components/ui/button'
import { Field, TextInput } from '../components/ui/Field'
import { useAuth } from '../features/auth/AuthProvider'

interface LoginLocationState {
  from?: string
}

/**
 * Email + password sign-in. On success the JWT is stored and the user is sent
 * back to the page they originally asked for (or the dashboard).
 */
export function LoginPage() {
  const { user, login } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const from = (location.state as LoginLocationState | null)?.from ?? '/'

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [pending, setPending] = useState(false)

  // Already signed in (e.g. back button) — don't show the form again.
  useEffect(() => {
    if (user) navigate(from, { replace: true })
  }, [user, from, navigate])

  if (user) return <Navigate to={from} replace />

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault()
    if (pending) return
    setError(null)
    setPending(true)
    try {
      await login(email.trim(), password)
      navigate(from, { replace: true })
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : 'Could not sign in. Check the API is running.',
      )
    } finally {
      setPending(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-canvas px-4 py-10">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex items-center justify-center gap-2.5">
          <div className="flex h-9 w-9 items-center justify-center rounded-md bg-action text-sm font-bold text-action-foreground">
            KA
          </div>
          <div>
            <p className="text-sm font-semibold text-ink">Knowledge Assistant</p>
            <p className="text-xs text-ink-secondary">Beta</p>
          </div>
        </div>

        <div className="rounded-lg border border-line bg-panel p-6 shadow-sm">
          <h1 className="text-lg font-semibold tracking-tight text-ink">
            Sign in
          </h1>
          <p className="mt-1 text-sm text-ink-secondary">
            Use the account provisioned for your organization.
          </p>

          <form onSubmit={onSubmit} className="mt-5 space-y-4">
            <Field label="Email" htmlFor="login-email">
              <TextInput
                id="login-email"
                type="email"
                autoComplete="username"
                required
                autoFocus
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                placeholder="you@company.com"
              />
            </Field>

            <Field label="Password" htmlFor="login-password">
              <TextInput
                id="login-password"
                type="password"
                autoComplete="current-password"
                required
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                placeholder="••••••••"
              />
            </Field>

            {error && (
              <p
                role="alert"
                className="rounded-md border border-status-bad/30 bg-status-bad-soft px-3 py-2 text-sm text-status-bad"
              >
                {error}
              </p>
            )}

            <Button type="submit" className="w-full" loading={pending}>
              {pending ? 'Signing in…' : 'Sign in'}
            </Button>
          </form>

        </div>

        <p className="mt-4 text-center text-xs text-ink-subtle">
          Access is enforced by the database per organization and role.
        </p>
      </div>
    </div>
  )
}
