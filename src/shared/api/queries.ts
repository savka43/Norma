import { useQuery } from '@tanstack/react-query'
import type { QueryClient } from '@tanstack/react-query'
import { ApiError, get } from './client'

export function useApi<T>(path: string, enabled = true) {
  return useQuery({
    queryKey: [path],
    queryFn: ({ signal }) => get<T>(path, signal),
    enabled,
    retry: (attempt, error) =>
      attempt < 1 && error instanceof ApiError && error.status >= 500,
  })
}

export function invalidatePaths(client: QueryClient, ...paths: string[]) {
  return client.invalidateQueries({
    predicate: ({ queryKey: [key] }) =>
      typeof key === 'string' &&
      paths.some(
        (path) =>
          key === path ||
          key.startsWith(`${path}/`) ||
          key.startsWith(`${path}?`),
      ),
  })
}
