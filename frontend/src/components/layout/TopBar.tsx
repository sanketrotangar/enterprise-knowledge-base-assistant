interface TopBarProps {
  title: string
  onOpenSidebar: () => void
  actions?: React.ReactNode
}

export function TopBar({ title, onOpenSidebar, actions }: TopBarProps) {
  return (
    <header className="flex h-14 shrink-0 items-center gap-3 border-b border-line bg-panel px-4 sm:px-6">
      <button
        type="button"
        onClick={onOpenSidebar}
        aria-label="Open navigation"
        className="rounded-md p-1.5 text-ink-secondary hover:bg-panel-muted hover:text-ink md:hidden"
      >
        <svg
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth={1.8}
          strokeLinecap="round"
          className="h-5 w-5"
          aria-hidden="true"
        >
          <path d="M3.75 6.75h16.5M3.75 12h16.5m-16.5 5.25h16.5" />
        </svg>
      </button>

      <h1 className="truncate text-base font-semibold text-ink">{title}</h1>

      {actions && <div className="ml-auto flex items-center gap-2">{actions}</div>}
    </header>
  )
}
