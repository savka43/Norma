import { useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError, get, send } from '../../shared/api/client'
import { invalidatePaths } from '../../shared/api/queries'
import type { Document, Lease, Version } from '../../shared/api/types'
import type { EditorContent } from './serialization'

export type LocalDraft = { baseRevision: number; content: EditorContent }

export function draftKey(userId: string, documentId: string) {
  return `norma:document-draft:${userId}:${documentId}`
}

export function readLocalDraft(key: string): LocalDraft | null {
  try {
    const value = JSON.parse(
      localStorage.getItem(key) ?? 'null',
    ) as LocalDraft | null
    if (
      value &&
      Number.isInteger(value.baseRevision) &&
      Array.isArray(value.content?.root?.children) &&
      value.content.root.children.length
    ) {
      return value
    }
  } catch {
    // Unavailable browser storage does not prevent editing.
  }
  return null
}

export function clearLocalDraft(key: string) {
  try {
    localStorage.removeItem(key)
  } catch {
    // Storage can be unavailable in private or restricted sessions.
  }
}

type Status = 'opening' | 'ready' | 'saving' | 'retry' | 'conflict'
type ImageAsset = { id: string; width: number; height: number }

function leaseHeaders(lease: Lease) {
  return { 'X-Edit-Lease': lease.lease_id }
}

export function useEditing(
  initial: Document,
  key: string,
  initialDraft: EditorContent | null,
  allowed: boolean,
) {
  const client = useQueryClient()
  const path = `/documents/${initial.id}`
  const leasePath = `${path}/edit-lease`
  const queryKey = `/theses/${initial.thesis_id}/document`
  const model = useRef({
    lease: null as Lease | null,
    revision: initial.revision,
    draft: initialDraft,
    mounted: false,
    acquiring: false,
  })
  const inFlight = useRef<Promise<boolean> | null>(null)
  const [lease, setLease] = useState<Lease | null>(null)
  const [status, setStatus] = useState<Status>('opening')
  const [error, setError] = useState<unknown>(null)
  const [dirty, setDirty] = useState(initialDraft !== null)
  const [change, setChange] = useState(0)
  const [storageFailed, setStorageFailed] = useState(false)

  const persist = useCallback(() => {
    const { draft, revision } = model.current
    if (!draft) {
      clearLocalDraft(key)
      return
    }
    try {
      localStorage.setItem(
        key,
        JSON.stringify({ baseRevision: revision, content: draft }),
      )
      if (model.current.mounted) setStorageFailed(false)
    } catch {
      if (model.current.mounted) setStorageFailed(true)
    }
  }, [key])

  const reportError = useCallback((failure: unknown) => {
    if (!model.current.mounted) return
    setError(failure)
    setStatus(
      failure instanceof ApiError && failure.status === 409
        ? 'conflict'
        : 'retry',
    )
  }, [])

  const release = useCallback(
    (owned: Lease) =>
      send(leasePath, {
        method: 'DELETE',
        headers: leaseHeaders(owned),
        keepalive: true,
      }).catch(() => undefined),
    [leasePath],
  )

  const acquire = useCallback(async () => {
    const state = model.current
    if (!allowed || state.acquiring || state.lease) return
    state.acquiring = true
    setStatus('opening')
    setError(null)
    let owned: Lease | null = null
    try {
      owned = await send<Lease>(leasePath, { method: 'POST' })
      const fresh = await get<Document>(path)
      if (fresh.revision !== state.revision) {
        throw new ApiError(
          409,
          'На сервере уже есть более свежий документ. Перечитайте его, чтобы восстановить черновик.',
        )
      }
      if (!state.mounted) return
      state.lease = owned
      setLease(owned)
      owned = null
      setStatus('ready')
    } catch (failure) {
      reportError(failure)
    } finally {
      state.acquiring = false
      if (owned) void release(owned)
    }
  }, [allowed, leasePath, path, release, reportError])

  useEffect(() => {
    const state = model.current
    state.mounted = true
    // Delay the first request until React's development effect replay settles.
    const timer = window.setTimeout(() => void acquire(), 0)
    const pageHide = () => {
      if (state.lease) void release(state.lease)
    }
    const pageShow = (event: PageTransitionEvent) => {
      if (event.persisted) window.location.reload()
    }
    window.addEventListener('pagehide', pageHide)
    window.addEventListener('pageshow', pageShow)
    return () => {
      window.clearTimeout(timer)
      window.removeEventListener('pagehide', pageHide)
      window.removeEventListener('pageshow', pageShow)
      state.mounted = false
      const owned = state.lease
      state.lease = null
      if (owned) {
        void (inFlight.current ?? Promise.resolve()).finally(() =>
          release(owned),
        )
      }
    }
  }, [acquire, release])

  useEffect(() => {
    if (!lease) return
    const duration =
      Date.parse(lease.expires_at) - Date.parse(lease.acquired_at)
    const interval = Math.max(1000, Math.min(30_000, duration / 3))
    const timer = window.setInterval(() => {
      void send(leasePath + '/renew', {
        method: 'POST',
        headers: leaseHeaders(lease),
      }).catch((failure: unknown) => {
        if (!model.current.mounted || model.current.lease !== lease) return
        if (failure instanceof ApiError && failure.status === 409) {
          model.current.lease = null
          setLease(null)
          reportError(
            new ApiError(
              409,
              'Доступ к редактированию истёк. Получите его снова.',
            ),
          )
        }
      })
    }, interval)
    return () => window.clearInterval(timer)
  }, [lease, leasePath, reportError])

  useEffect(() => {
    if (!dirty || !storageFailed) return
    const warn = (event: BeforeUnloadEvent) => event.preventDefault()
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [dirty, storageFailed])

  const save = useCallback((): Promise<boolean> => {
    const state = model.current
    if (inFlight.current) return inFlight.current
    if (!state.lease) return Promise.resolve(false)
    if (!state.draft) return Promise.resolve(true)

    const draft = state.draft
    const task = send<Document>(path, {
      method: 'PUT',
      headers: leaseHeaders(state.lease),
      json: {
        content: draft,
        schema_version: 4,
        expected_revision: state.revision,
        template_version_id: initial.template_version_id,
      },
    })
      .then(
        (saved) => {
          state.revision = saved.revision
          if (state.draft === draft) state.draft = null
          persist()
          client.setQueryData([queryKey], saved)
          if (state.mounted) {
            setDirty(state.draft !== null)
            setStatus('ready')
          }
          return true
        },
        (failure: unknown) => {
          reportError(failure)
          return false
        },
      )
      .finally(() => {
        inFlight.current = null
      })
    inFlight.current = task
    setError(null)
    setStatus('saving')
    return task
  }, [
    client,
    initial.template_version_id,
    path,
    persist,
    queryKey,
    reportError,
  ])

  useEffect(() => {
    if (!dirty || !lease || status !== 'ready') return
    const timer = window.setTimeout(() => void save(), 650)
    return () => window.clearTimeout(timer)
  }, [change, dirty, lease, save, status])

  function update(content: EditorContent) {
    model.current.draft = content
    persist()
    setDirty(true)
    setChange((count) => count + 1)
  }

  async function beforeVersionAction() {
    while (model.current.draft) {
      if (!(await save())) return null
    }
    const { lease: owned, revision } = model.current
    return owned ? { headers: leaseHeaders(owned), revision } : null
  }

  async function createVersion() {
    const current = await beforeVersionAction()
    if (!current) return null
    const version = await send<Version>(`${path}/versions`, {
      method: 'POST',
      headers: current.headers,
      json: { expected_revision: current.revision },
    })
    await invalidatePaths(client, `${path}/versions`)
    return version
  }

  async function uploadImage(file: File) {
    const current = await beforeVersionAction()
    if (!current) return null
    return send<ImageAsset>(
      `${path}/assets?expected_revision=${current.revision}`,
      {
        method: 'POST',
        headers: { ...current.headers, 'Content-Type': file.type },
        body: file,
      },
    )
  }

  return {
    lease,
    status,
    error,
    dirty,
    storageFailed,
    acquire,
    update,
    save,
    createVersion,
    uploadImage,
  }
}
