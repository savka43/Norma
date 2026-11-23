import { useForm } from '@tanstack/react-form'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useRef, useState } from 'react'
import { send } from '../../shared/api/client'
import { invalidatePaths, useApi } from '../../shared/api/queries'
import type {
  Comment,
  CommentAnchor,
  Page,
  Version,
} from '../../shared/api/types'
import {
  Button,
  Chip,
  date,
  ErrorNotice,
  Notice,
  Pager,
  Panel,
} from '../../shared/ui/Ui'
import w from '../../shared/ui/Workspace.module.css'
import type { TextBlock } from './snapshot'
import styles from './Review.module.css'

function ComposeComment({
  path,
  blocks,
  onCreated,
}: {
  path: string
  blocks: TextBlock[]
  onCreated: () => void
}) {
  const textarea = useRef<HTMLTextAreaElement>(null)
  const [selected, setSelected] = useState(blocks[0]?.id ?? '')
  const [selection, setSelection] = useState({ start: 0, end: 0 })
  const block = blocks.find((item) => item.id === selected)
  const quote = block?.text.slice(selection.start, selection.end) ?? ''
  const client = useQueryClient()
  const create = useMutation({
    mutationFn: ({
      body,
      anchor,
      quote,
    }: {
      body: string
      anchor: CommentAnchor
      quote: string
    }) =>
      send<Comment>(path, { method: 'POST', json: { body, anchor, quote } }),
    onSuccess: async () => {
      onCreated()
      await invalidatePaths(client, path)
    },
  })
  const form = useForm({
    defaultValues: { body: '' },
    onSubmit: async ({ value, formApi }) => {
      if (!block || !quote || quote.length > 10000) return
      try {
        await create.mutateAsync({
          ...value,
          quote,
          anchor: {
            block_id: block.id,
            offset_start: selection.start,
            offset_end: selection.end,
          },
        })
        formApi.reset()
      } catch {
        // Preserve the remark for correction.
      }
    },
  })
  if (!blocks.length)
    return <p>В версии нет текста, к которому можно привязать замечание.</p>
  return (
    <details>
      <summary className={w.toggle}>Написать замечание</summary>
      <form
        className={w.form}
        onSubmit={(event) => {
          event.preventDefault()
          void form.handleSubmit()
        }}
      >
        <label className={w.label}>
          Абзац или элемент
          <select
            value={selected}
            onChange={(event) => {
              setSelected(event.target.value)
              setSelection({ start: 0, end: 0 })
            }}
          >
            {blocks.map((item, index) => (
              <option key={item.id} value={item.id}>
                {index + 1}. {item.text.slice(0, 90)}
              </option>
            ))}
          </select>
        </label>
        <label className={w.label}>
          Выделите фрагмент для замечания
          <textarea
            ref={textarea}
            readOnly
            rows={4}
            value={block?.text ?? ''}
            onSelect={(event) =>
              setSelection({
                start: event.currentTarget.selectionStart,
                end: event.currentTarget.selectionEnd,
              })
            }
          />
        </label>
        <div>
          <Button
            variant="secondary"
            onClick={() => {
              if (!textarea.current || !block) return
              textarea.current.focus()
              textarea.current.select()
              setSelection({ start: 0, end: block.text.length })
            }}
          >
            Выделить весь фрагмент
          </Button>
        </div>
        {quote.length > 10000 && (
          <Notice error>Выберите фрагмент короче 10 000 символов.</Notice>
        )}
        <form.Field name="body">
          {(field) => (
            <label className={w.label}>
              Текст замечания
              <textarea
                rows={3}
                required
                maxLength={10000}
                value={field.state.value}
                onChange={(event) => field.handleChange(event.target.value)}
              />
            </label>
          )}
        </form.Field>
        <ErrorNotice error={create.error} />
        <Button
          type="submit"
          disabled={!quote || quote.length > 10000 || create.isPending}
        >
          Оставить замечание
        </Button>
      </form>
    </details>
  )
}

export function Comments({
  version,
  supervisor,
  blocks,
  onJump,
}: {
  version: Version
  supervisor: boolean
  blocks: TextBlock[]
  onJump: (blockId: string) => void
}) {
  const path = `/document-versions/${version.id}/comments`
  const [offset, setOffset] = useState(0)
  const [all, setAll] = useState(false)
  const limit = 15
  // The review is of a fixed snapshot, even when a remark can't be located in the working draft.
  const comments = useApi<Page<Comment>>(
    `${path}?include_detached=true&include_resolved=${all}&limit=${limit}&offset=${offset}`,
  )
  const client = useQueryClient()
  const resolve = useMutation({
    mutationFn: (comment: Comment) =>
      send(`/comments/${comment.id}`, {
        method: 'PATCH',
        json: { status: 'resolved', expected_revision: comment.revision },
      }),
    onSettled: () => invalidatePaths(client, path),
  })
  return (
    <Panel
      title="Замечания"
      action={
        <label>
          <input
            type="checkbox"
            checked={all}
            onChange={(event) => {
              setAll(event.target.checked)
              setOffset(0)
            }}
          />{' '}
          Показать закрытые
        </label>
      }
    >
      <ErrorNotice error={comments.error ?? resolve.error} />
      {comments.isPending && <Notice>Загружаем замечания…</Notice>}
      {comments.data && (
        <>
          {!comments.data.items.length && (
            <p>
              {offset
                ? 'На этой странице нет замечаний.'
                : 'Замечаний к этой версии нет.'}
            </p>
          )}
          <ul className={w.list}>
            {comments.data.items.map((comment) => (
              <li key={comment.id}>
                <div className={w.row}>
                  <small>{date(comment.created_at)}</small>
                  <Chip
                    tone={comment.status === 'resolved' ? 'green' : 'orange'}
                  >
                    {comment.status === 'resolved' ? 'Закрыто' : 'Открыто'}
                  </Chip>
                </div>
                <blockquote className={styles.excerpt}>
                  {comment.quote}
                </blockquote>
                <p className={styles.body}>{comment.body}</p>
                <div className={w.actions}>
                  <Button
                    variant="quiet"
                    onClick={() => onJump(comment.anchor.block_id)}
                  >
                    К цитате в версии
                  </Button>
                  {comment.status === 'open' && (
                    <Button
                      variant="secondary"
                      disabled={resolve.isPending}
                      onClick={() => resolve.mutate(comment)}
                    >
                      Отметить исправленным
                    </Button>
                  )}
                </div>
              </li>
            ))}
          </ul>
          <Pager
            offset={offset}
            limit={limit}
            size={comments.data.items.length}
            onChange={setOffset}
          />
        </>
      )}
      {supervisor && (
        <ComposeComment
          path={path}
          blocks={blocks}
          onCreated={() => setOffset(0)}
        />
      )}
    </Panel>
  )
}
