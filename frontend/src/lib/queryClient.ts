import { QueryClient } from '@tanstack/react-query'

/**
 * Conservative defaults: data is refetched on window focus (fast because the
 * API is local) but never polled aggressively. Individual queries override
 * staleTime/refetchInterval where it makes sense.
 */
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 15_000,
      refetchOnWindowFocus: true,
      retry: 1,
    },
  },
})
