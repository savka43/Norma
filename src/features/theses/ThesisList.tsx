import { useState } from 'react'
import { Link, Navigate } from 'react-router-dom'
import { useApi } from '../../shared/api/queries'
import type { Page, Thesis } from '../../shared/api/types'
import { Button, date, ErrorNotice, Notice, Pager } from '../../shared/ui/Ui'
import w from '../../shared/ui/Workspace.module.css'
import styles from './ThesisPage.module.css'

export function Progress({ thesis }: { thesis: Thesis }) {
  if (thesis.progress_percent === null) return <small>Этапов пока нет</small>
  return (
    <div className={w.progress}>
      <span>
        <strong>{Math.round(thesis.progress_percent)}%</strong>{' '}
        <small>
          {thesis.completed_stages} из {thesis.total_stages} этапов
        </small>
      </span>
      <progress
        aria-label="Прогресс ВКР"
        max={100}
        value={thesis.progress_percent}
      />
    </div>
  )
}

export function StudentHome() {
  const thesis = useApi<Page<Thesis>>('/theses?limit=1')
  const assigned = thesis.data?.items[0]
  if (assigned) return <Navigate to={`/works/${assigned.id}`} replace />

  return (
    <div className={w.page}>
      {!thesis.isSuccess && <h1>Моя ВКР</h1>}
      {thesis.isPending && <Notice>Открываем ВКР…</Notice>}
      {thesis.error && (
        <div className={w.stack}>
          <ErrorNotice error={thesis.error} />
          <div>
            <Button onClick={() => void thesis.refetch()}>Повторить</Button>
          </div>
        </div>
      )}
      {thesis.isSuccess && (
        <section className={styles.empty} aria-labelledby="assignment-heading">
          <h1 id="assignment-heading">
            Руководитель ещё не назначил вам тему ВКР.
          </h1>
          <p>
            После назначения здесь появятся этапы, сроки и рабочий документ.
          </p>
          <Button
            variant="secondary"
            disabled={thesis.isFetching}
            onClick={() => void thesis.refetch()}
          >
            Проверить назначение
          </Button>
        </section>
      )}
    </div>
  )
}

export function ThesisList() {
  const [offset, setOffset] = useState(0)
  const limit = 25
  const list = useApi<Page<Thesis>>(`/theses?limit=${limit}&offset=${offset}`)
  return (
    <div className={w.page}>
      <header className={w.heading}>
        <h1>Выпускные работы</h1>
      </header>
      <section aria-label="Работы студентов">
        <ErrorNotice error={list.error} />
        {list.isPending && <Notice>Загружаем работы…</Notice>}
        {list.data && (
          <>
            {!list.data.items.length && (
              <p>
                {offset
                  ? 'На этой странице нет работ.'
                  : 'Создайте ВКР для студента в разделе «Группы».'}
              </p>
            )}
            <ul className={w.list}>
              {list.data.items.map((thesis) => (
                <li key={thesis.id} className={w.row}>
                  <div>
                    <Link to={`/works/${thesis.id}`}>{thesis.title}</Link>
                    <p className={w.muted}>
                      Срок: {date(thesis.due_date)}
                      {thesis.is_overdue ? ' · Просрочено' : ''}
                    </p>
                  </div>
                  <Progress thesis={thesis} />
                </li>
              ))}
            </ul>
            <Pager
              limit={limit}
              offset={offset}
              size={list.data.items.length}
              onChange={setOffset}
            />
          </>
        )}
      </section>
    </div>
  )
}
