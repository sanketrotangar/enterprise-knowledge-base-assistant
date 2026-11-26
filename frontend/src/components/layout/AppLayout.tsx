import { useState } from 'react'
import { Outlet } from 'react-router-dom'
import { SideBar } from './SideBar'
import { TopBar } from './TopBar'
import { Badge } from '../ui/badge'
import { Button } from '../ui/button'
import { SystemHealthFooter } from '../../features/SystemHealthFooter'
import { useAuth } from '../../features/auth/AuthProvider'
import { PageTitleContext, usePageTitle } from '../../features/usePageTitle'

/**
 * Application shell: persistent sidebar + topbar + routed content.
 * - Desktop (md+): sidebar is permanently visible.
 * - Mobile: sidebar slides over content behind a backdrop; body scroll is
 *   locked while it's open.
 * Page titles are provided by each page through PageTitleContext.
 */
export function AppLayout() {
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const { title, setTitle } = usePageTitle('')
  const { user, logout } = useAuth()

  const accountActions = user ? (
    <div className="flex items-center gap-2">
      <span className="hidden max-w-[16rem] truncate text-xs text-ink-secondary sm:block">
        {user.email}
      </span>
      <Badge tone="action" className="capitalize">
        {user.role}
      </Badge>
      <Button variant="ghost" size="sm" onClick={logout}>
        Sign out
      </Button>
    </div>
  ) : undefined

  return (
    <PageTitleContext.Provider value={{ title, setTitle }}>
      <div className="flex h-screen overflow-hidden">
        {/* Desktop sidebar */}
        <aside className="hidden w-64 shrink-0 border-r border-line bg-panel md:block">
          <SideBar footer={<SystemHealthFooter />} />
        </aside>

        {/* Mobile sidebar drawer */}
        {sidebarOpen && (
          <div className="fixed inset-0 z-40 md:hidden" role="dialog" aria-modal="true" aria-label="Navigation">
            <div
              className="absolute inset-0 bg-ink/40"
              onClick={() => setSidebarOpen(false)}
            />
            <div className="absolute inset-y-0 left-0 w-64 border-r border-line bg-panel shadow-xl">
              <SideBar
                onNavigate={() => setSidebarOpen(false)}
                footer={<SystemHealthFooter />}
              />
            </div>
          </div>
        )}

        {/* Main column */}
        <div className="flex min-w-0 flex-1 flex-col bg-canvas">
          <TopBar
            title={title || 'Dashboard'}
            onOpenSidebar={() => setSidebarOpen(true)}
            actions={accountActions}
          />
          <main className="flex-1 overflow-y-auto">
            <Outlet />
          </main>
        </div>
      </div>
    </PageTitleContext.Provider>
  )
}
