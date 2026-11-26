import { createContext, useContext } from 'react'

interface PageTitleValue {
  title: string
  setTitle: (title: string) => void
}

export const PageTitleContext = createContext<PageTitleValue>({
  title: '',
  setTitle: () => {},
})

/** Convenience hook for pages: const { setTitle } = usePageTitle(). */
export function usePageTitle(fallback: string) {
  const value = useContext(PageTitleContext)
  return { ...value, fallback }
}
