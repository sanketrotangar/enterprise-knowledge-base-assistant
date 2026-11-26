import type { ComponentType } from 'react'
import { NavLink } from 'react-router-dom'
import {
  DocumentIcon,
  MagnifyingGlassIcon,
  SquaresIcon,
  UserCircleIcon,
  XMarkIcon,
} from '../icons'

interface NavItem {
  to: string
  label: string
  icon: ComponentType<{ className?: string }>
  /** Section exists in the product plan but its backend phase hasn't landed. */
  comingSoon?: boolean
}

interface NavSection {
  heading: string
  items: NavItem[]
}

/**
 * Navigation covers the full product scope: admin sections are live (or
 * degrade to coming-soon) now; employee sections are placeholders until the
 * user side is built.
 */
/** Beta nav only. History/feedback/audit parked — UI redesign allowed in slice 6. */
const SECTIONS: NavSection[] = [
  {
    heading: 'Workspace',
    items: [
      { to: '/', label: 'Dashboard', icon: SquaresIcon },
      { to: '/documents', label: 'Documents', icon: DocumentIcon },
      { to: '/search', label: 'Ask', icon: MagnifyingGlassIcon },
      { to: '/admin/users', label: 'Users & Roles', icon: UserCircleIcon, comingSoon: true },
    ],
  },
]

export function SideBar({
  onNavigate,
  footer,
}: {
  onNavigate?: () => void
  footer?: React.ReactNode
}) {
  return (
    <div className="flex h-full flex-col bg-panel">
      {/* Brand */}
      <div className="flex h-14 shrink-0 items-center gap-2.5 border-b border-line px-4">
        <div className="flex h-8 w-8 items-center justify-center rounded-md bg-action text-sm font-bold text-action-foreground">
          KA
        </div>
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold text-ink">Knowledge Assistant</p>
          <p className="truncate text-xs text-ink-secondary">Beta</p>
        </div>
        {/* Mobile close */}
        <button
          type="button"
          onClick={onNavigate}
          aria-label="Close navigation"
          className="ml-auto rounded-md p-1.5 text-muted hover:bg-subtle hover:text-fg md:hidden"
        >
          <XMarkIcon className="h-5 w-5" />
        </button>
      </div>

      {/* Nav */}
      <nav aria-label="Main navigation" className="flex-1 space-y-6 overflow-y-auto px-3 py-4">
        {SECTIONS.map((section) => (
          <div key={section.heading}>
            <p className="px-2 pb-2 text-xs font-semibold uppercase tracking-wide text-ink-subtle">
              {section.heading}
            </p>
            <ul role="list" className="space-y-1">
              {section.items.map((item) => (
                <li key={item.to}>
                  {item.comingSoon ? (
                    <SoonNavItem item={item} />
                  ) : (
                    <ActiveNavItem item={item} onNavigate={onNavigate} />
                  )}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </nav>

      {/* Footer (system health indicator) */}
      {footer && <div className="border-t border-line p-3">{footer}</div>}
    </div>
  )
}

function ActiveNavItem({
  item,
  onNavigate,
}: {
  item: NavItem
  onNavigate?: () => void
}) {
  const Icon = item.icon
  return (
    <NavLink
      to={item.to}
      onClick={onNavigate}
      className={({ isActive }) =>
        `flex items-center gap-3 rounded-md px-2.5 py-2 text-sm font-medium transition-colors ${
          isActive
            ? 'bg-action-soft text-action'
            : 'text-ink hover:bg-panel-muted'
        }`
      }
    >
      <Icon className="h-[18px] w-[18px] shrink-0" />
      {item.label}
    </NavLink>
  )
}

function SoonNavItem({ item }: { item: NavItem }) {
  const Icon = item.icon
  return (
    <button
      type="button"
      onClick={openComingSoon}
      className="flex w-full items-center gap-3 rounded-md px-2.5 py-2 text-sm font-medium text-muted transition-colors hover:bg-subtle hover:text-fg"
    >
      <Icon className="h-[18px] w-[18px] shrink-0" />
      <span className="flex-1 text-left">{item.label}</span>
      <span className="rounded-full border border-default bg-subtle px-1.5 py-px text-[10px] font-medium uppercase tracking-wide text-muted">
        Soon
      </span>
    </button>
  )
}

// The "coming soon" modal lives in App to avoid duplicate modals per page.
// Nav buttons call through this registered opener (set once by App).
let comingSoonOpener: (() => void) | null = null
export function setComingSoonOpener(fn: () => void) {
  comingSoonOpener = fn
}
function openComingSoon() {
  comingSoonOpener?.()
}
