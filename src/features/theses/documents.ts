import { ApiError, get, send } from '../../shared/api/client'
import type { Document, Lease } from '../../shared/api/types'

export const DOCX =
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document'

export const versionPageSize = 15

export function versionListPath(documentId: string, offset = 0) {
  return `/documents/${documentId}/versions?limit=${versionPageSize}&offset=${offset}`
}

export async function getDocument(
  thesisId: string,
  signal: AbortSignal,
): Promise<Document | null> {
  try {
    return await get<Document>(`/theses/${thesisId}/document`, signal)
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null
    throw error
  }
}

export async function withLease<T>(
  documentId: string,
  action: (headers: Record<string, string>) => Promise<T>,
) {
  const path = `/documents/${documentId}/edit-lease`
  const lease = await send<Lease>(path, { method: 'POST' })
  const headers = { 'X-Edit-Lease': lease.lease_id }
  try {
    return await action(headers)
  } finally {
    await send(path, { method: 'DELETE', headers }).catch(() => undefined)
  }
}
