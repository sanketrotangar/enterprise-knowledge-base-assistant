import type { ReactNode } from 'react'
import { Button } from './button'

interface StatePanelProps {
  title: string
  message: string
  icon?: ReactNode
  action?: ReactNode
}

function StatePanel({ title, message, icon, action }: StatePanelProps) {
  return (
    <div role="status" className="flex flex-col items-center px-6 py-14 text-center">
      {icon && <div className="mb-3 text-muted">{icon}</div>}
      <h3 className="text-sm font-medium text-fg">{title}</h3>
      <p className="mt-1 max-w-sm text-sm text-muted">{message}</p>
      {action && <div className="mt-4">{action}</div>}
    </div>
  )
}

export function ErrorState({
  message,
  onRetry,
}: {
  message: string
  onRetry?: () => void
}) {
  return (
    <StatePanel
      title="Something went wrong"
      message={message}
      action={
        onRetry ? (
          <Button variant="secondary" size="sm" onClick={onRetry}>
            Try again
          </Button>
        ) : undefined
      }
    />
  )
}

export function EmptyState({
  title,
  message,
  action,
}: {
  title: string
  message: string
  action?: ReactNode
}) {
  return <StatePanel title={title} message={message} action={action} />
}
