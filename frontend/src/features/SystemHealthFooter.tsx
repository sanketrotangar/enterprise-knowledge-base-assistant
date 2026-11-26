import { useHealth } from './useSystemHealth'

/** Sidebar footer: backend liveness at a glance. */
export function SystemHealthFooter() {
  const { data, isError } = useHealth()

  const online = !isError && data?.status === 'healthy'
  const label = online ? 'API online' : 'API offline'
  const dotClass = online ? 'bg-emerald-500' : 'bg-red-500'
  const textClass = online ? 'text-fg' : 'text-danger-text'

  return (
    <div className="flex items-center gap-2 rounded-md bg-subtle px-2.5 py-2">
      <span className="relative flex h-2 w-2 shrink-0">
        <span className={`absolute inline-flex h-full w-full rounded-full ${dotClass} ${online ? 'animate-ping opacity-60' : ''}`} />
        <span className={`relative inline-flex h-2 w-2 rounded-full ${dotClass}`} />
      </span>
      <span className={`text-xs font-medium ${textClass}`}>{label}</span>
    </div>
  )
}
