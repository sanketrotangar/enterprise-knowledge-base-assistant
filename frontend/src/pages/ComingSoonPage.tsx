import { useEffect } from 'react'
import { usePageTitle } from '../features/usePageTitle'
import { ComingSoon } from '../components/shared/ComingSoon'

interface ComingSoonPageProps {
  title: string
  phase: string
}

/** Generic page shell for features not yet implemented in the backend. */
export function ComingSoonPage({ title, phase }: ComingSoonPageProps) {
  const { setTitle } = usePageTitle('')
  useEffect(() => setTitle(title), [setTitle, title])

  return <ComingSoon title={title} phase={phase} />
}
