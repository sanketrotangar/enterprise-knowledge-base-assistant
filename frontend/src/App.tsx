import { useCallback, useEffect, useState } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { AppLayout } from './components/layout/AppLayout'
import { setComingSoonOpener } from './components/layout/SideBar'
import { Modal } from './components/ui/Modal'
import { Button } from './components/ui/button'
import { AuthProvider, RequireAuth } from './features/auth/AuthProvider'
import { DashboardPage } from './pages/DashboardPage'
import { DocumentsPage } from './pages/DocumentsPage'
import { LoginPage } from './pages/LoginPage'
import { SearchPage } from './pages/SearchPage'
import { ComingSoonPage } from './pages/ComingSoonPage'

/**
 * Beta routes (docs/build.md). Everything except /login requires a JWT.
 */
export default function App() {
  return (
    <AuthProvider>
      <AppRoutes />
    </AuthProvider>
  )
}

function AppRoutes() {
  const [comingSoon, setComingSoon] = useState(false)

  const openComingSoon = useCallback(() => setComingSoon(true), [])
  useEffect(() => {
    setComingSoonOpener(openComingSoon)
  }, [openComingSoon])

  const closeComingSoon = useCallback(() => setComingSoon(false), [])

  return (
    <>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route
          element={
            <RequireAuth>
              <AppLayout />
            </RequireAuth>
          }
        >
          <Route index element={<DashboardPage />} />
          <Route path="documents" element={<DocumentsPage />} />
          <Route path="search" element={<SearchPage />} />
          <Route
            path="admin/users"
            element={
              <ComingSoonPage
                title="Users & Roles"
                phase="Not in the beta build — see docs/build.md"
              />
            }
          />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>

      <Modal open={comingSoon} onClose={closeComingSoon} title="Coming soon">
        <div className="space-y-3">
          <p className="text-sm text-muted">
            This section is not in the beta build yet. See docs/build.md.
          </p>
          <div className="flex justify-end">
            <Button size="sm" onClick={closeComingSoon}>
              Got it
            </Button>
          </div>
        </div>
      </Modal>
    </>
  )
}
