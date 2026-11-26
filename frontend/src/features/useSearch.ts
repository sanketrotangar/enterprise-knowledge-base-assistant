import { useMutation } from '@tanstack/react-query'
import { search } from '../api/search'
import type { SearchRequest, SearchResponse } from '../types/api'

/** Search / ask: POST /api/v1/search (answer + sources). No history cache. */
export function useSearch() {
  return useMutation({
    mutationFn: (request: SearchRequest): Promise<SearchResponse> =>
      search(request),
  })
}
