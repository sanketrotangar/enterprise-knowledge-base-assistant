import { useQuery } from '@tanstack/react-query'
import { getDetailedHealth, getHealth } from '../api/health'

export interface ServiceHealthMap {
  database?: string
  redis?: string
  qdrant?: string
  celery?: string
}

/** Basic liveness poll — drives the sidebar status dot. */
export function useHealth() {
  return useQuery({
    queryKey: ['health'],
    queryFn: getHealth,
    refetchInterval: 30_000,
    staleTime: 15_000,
    retry: false, // offline backend should show "offline", not spinner forever
  })
}

/** Detailed per-service health — drives the dashboard service cards. */
export function useDetailedHealth() {
  return useQuery({
    queryKey: ['health-detailed'],
    queryFn: getDetailedHealth,
    refetchInterval: 30_000,
    staleTime: 15_000,
    retry: false,
  })
}
