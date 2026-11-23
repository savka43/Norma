import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { get, send } from '../../shared/api/client'
import { invalidatePaths, useApi } from '../../shared/api/queries'
import type { Check, Page, Report } from '../../shared/api/types'
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
import styles from './Review.module.css'

const statuses: Record<Check['status'], string> = {
  queued: 'В очереди',
  uploading: 'Загрузка',
  uploaded: 'Загружено',
  starting: 'Запуск',
  checking: 'Проверяется',
  completed: 'Завершена',
  failed: 'Ошибка',
}
const terminal = (status: Check['status']) =>
  status === 'failed' || status === 'completed'

function ReportView({ checkId }: { checkId: string }) {
  const result = useApi<Report>(`/plagiarism-checks/${checkId}/report`)
  return (
    <>
      <ErrorNotice error={result.error} />
      {result.isPending && <Notice>Загружаем отчёт…</Notice>}
      {result.data && (
        <div>
          <dl className={styles.measures}>
            {(
              [
                ['Оригинальность', result.data.originality_percent],
                ['Совпадения', result.data.similarity_percent],
                ['Цитирование', result.data.citation_percent],
                ['Самоцитирование', result.data.self_citation_percent],
              ] as const
            ).map(([label, value]) => (
              <div key={label}>
                <dt>{label}</dt>
                <dd>
                  {value == null
                    ? '—'
                    : `${value.toLocaleString('ru-RU', { maximumFractionDigits: 2 })}%`}
                </dd>
              </div>
            ))}
          </dl>
          {result.data.is_suspicious && (
            <Notice error>Сервис пометил документ как подозрительный.</Notice>
          )}
          <div className={w.actions}>
            {result.data.short_report_url && (
              <a
                href={result.data.short_report_url}
                target="_blank"
                rel="noreferrer"
              >
                Краткий отчёт
              </a>
            )}
            {result.data.readonly_report_url && (
              <a
                href={result.data.readonly_report_url}
                target="_blank"
                rel="noreferrer"
              >
                Полный отчёт для чтения
              </a>
            )}
          </div>
        </div>
      )}
    </>
  )
}

export function Plagiarism({
  versionId,
  student,
}: {
  versionId: string
  student: boolean
}) {
  const [offset, setOffset] = useState(0)
  const [confirm, setConfirm] = useState(false)
  const limit = 10
  const path = `/document-versions/${versionId}/plagiarism-checks`
  const pagePath = `${path}?limit=${limit}&offset=${offset}`
  const checks = useQuery({
    queryKey: [pagePath],
    queryFn: ({ signal }) => get<Page<Check>>(pagePath, signal),
    refetchInterval: (query) =>
      query.state.data?.items.some((item) => !terminal(item.status))
        ? 3000
        : false,
    retry: false,
  })
  const client = useQueryClient()
  const start = useMutation({
    mutationFn: () =>
      send<Check>(path, {
        method: 'POST',
        json: { confirm_demo_document: true },
      }),
    onSettled: () => invalidatePaths(client, path),
    onSuccess: () => {
      setOffset(0)
      setConfirm(false)
    },
  })
  const active = checks.data?.items.some((item) => !terminal(item.status))
  return (
    <Panel title="Заимствования">
      <ErrorNotice error={checks.error ?? start.error} />
      {checks.isPending && <Notice>Загружаем проверки…</Notice>}
      {checks.data && (
        <>
          {!checks.data.items.length && (
            <p>
              {offset
                ? 'На этой странице нет проверок.'
                : 'Эту версию ещё не проверяли.'}
            </p>
          )}
          <ul className={w.list}>
            {checks.data.items.map((check) => (
              <li key={check.id}>
                <div className={w.row}>
                  <span>{date(check.created_at)}</span>
                  <Chip
                    tone={
                      check.status === 'completed'
                        ? 'green'
                        : check.status === 'failed'
                          ? 'orange'
                          : 'blue'
                    }
                  >
                    {statuses[check.status]}
                  </Chip>
                </div>
                {check.error_detail && <p>{check.error_detail}</p>}
                {check.status === 'completed' && (
                  <details>
                    <summary className={w.toggle}>Результаты проверки</summary>
                    <ReportView checkId={check.id} />
                  </details>
                )}
              </li>
            ))}
          </ul>
          <Pager
            offset={offset}
            limit={limit}
            size={checks.data.items.length}
            onChange={setOffset}
          />
        </>
      )}
      {student && (
        <div className={`${w.stack} ${styles.action}`}>
          <label>
            <input
              type="checkbox"
              checked={confirm}
              onChange={(event) => setConfirm(event.target.checked)}
            />{' '}
            Версия содержит только демонстрационный текст без персональных
            данных.
          </label>
          <div>
            <Button
              disabled={
                !checks.data ||
                !confirm ||
                active ||
                start.isPending ||
                offset !== 0
              }
              onClick={() => start.mutate()}
            >
              Запустить проверку
            </Button>
          </div>
        </div>
      )}
    </Panel>
  )
}
