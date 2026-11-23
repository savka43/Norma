import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useApi } from '../../shared/api/queries'
import type { Page, Thesis, User } from '../../shared/api/types'
import { date, ErrorNotice, Notice, Pager, Panel } from '../../shared/ui/Ui'
import w from '../../shared/ui/Workspace.module.css'

export function Progress({ thesis }: { thesis: Thesis }) {
  return (
    <div className={w.progress}>
      <span>
        <strong>
          {thesis.progress_percent === null
            ? '—'
            : `${Math.round(thesis.progress_percent)}%`}
        </strong>{' '}
        <small>
          {thesis.completed_stages} из {thesis.total_stages} этапов
        </small>
      </span>
      <progress
        aria-label="Прогресс ВКР"
        max={100}
        value={thesis.progress_percent ?? 0}
      />
    </div>
  )
}

export function ThesisList({ role }: { role: User['role'] }) {
  const [offset, setOffset] = useState(0)
  const limit = 25
  const list = useApi<Page<Thesis>>(`/theses?limit=${limit}&offset=${offset}`)
  return (
    <div className={w.page}>
      <header className={w.heading}>
        <div>
          <p>Кабинет {role === 'student' ? 'студента' : 'руководителя'}</p>
          <h1>{role === 'student' ? 'Моя ВКР' : 'Выпускные работы'}</h1>
        </div>
      </header>
      <Panel title={role === 'student' ? 'Работа и этапы' : 'Работы студентов'}>
        <ErrorNotice error={list.error} />
        {list.isPending && <Notice>Загружаем работы…</Notice>}
        {list.data && (
          <>
            {!list.data.items.length && (
              <p>
                {offset
                  ? 'На этой странице нет работ.'
                  : role === 'student'
                    ? 'Руководитель ещё не назначил вам тему ВКР.'
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
      </Panel>
    </div>
  )
}
