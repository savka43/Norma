import { useQueries } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { get } from '../../shared/api/client'
import type { Comment, Page, Stage, Thesis } from '../../shared/api/types'
import { Button, Chip, date, ErrorNotice } from '../../shared/ui/Ui'
import s from './StudentOverview.module.css'

function RecentRemarks({
  stages,
  thesisId,
}: {
  stages: Stage[]
  thesisId: string
}) {
  const submissions = stages.filter((stage) => stage.submitted_version_id)
  const results = useQueries({
    queries: submissions.map((stage) => {
      const path =
        '/document-versions/' +
        stage.submitted_version_id +
        '/comments?include_detached=true&limit=3'
      return {
        queryKey: [path],
        queryFn: ({ signal }: { signal: AbortSignal }) =>
          get<Page<Comment>>(path, signal),
      }
    }),
  })
  const rows = results
    .flatMap((query, i) =>
      (query.data?.items ?? []).map((comment) => ({
        comment,
        stage: submissions[i],
      })),
    )
    .sort((a, b) => b.comment.created_at.localeCompare(a.comment.created_at))
    .slice(0, 3)
  const failed = results.find((query) => query.error)
  return (
    <section className={s.block}>
      <h2>Замечания руководителя</h2>
      {failed && (
        <>
          <ErrorNotice error={failed.error} />
          <Button variant="secondary" onClick={() => void failed.refetch()}>
            Повторить
          </Button>
        </>
      )}
      {results.some((query) => query.isPending) && (
        <p role="status">Загружаем замечания…</p>
      )}
      {rows.length ? (
        <ul className={s.rows}>
          {rows.map(({ comment, stage }) => (
            <li key={comment.id}>
              <div>
                <small>{stage.name}</small>
                <div>{comment.body}</div>
              </div>
              <Link
                to={`/works/${thesisId}/versions/${comment.version_id}?stage=${stage.id}#block-${comment.anchor.block_id}`}
              >
                К фрагменту
              </Link>
            </li>
          ))}
        </ul>
      ) : (
        !failed &&
        results.every((q) => q.isSuccess) && (
          <p>В последних отправках открытых замечаний нет.</p>
        )
      )}
    </section>
  )
}

export function StudentOverview({
  thesis,
  stages,
}: {
  thesis: Thesis
  stages?: Stage[]
}) {
  const current = stages?.find((stage) => stage.status !== 'completed')
  const deadlines = stages
    ?.filter((stage) => stage.status !== 'completed')
    .sort((a, b) => a.due_date.localeCompare(b.due_date))
    .slice(0, 3)
  return (
    <>
      <header className={s.heading}>
        <h1>Моя выпускная работа</h1>
      </header>
      <section className={s.summary}>
        <small>Тема ВКР</small>
        <h2>{thesis.title}</h2>
        <p>
          Срок сдачи{' '}
          <time dateTime={thesis.due_date}>{date(thesis.due_date)}</time>{' '}
          {thesis.is_overdue && <Chip tone="orange">Просрочено</Chip>}
        </p>
        {stages &&
          (stages.length ? (
            <ol className={s.segments} aria-label="План ВКР">
              {stages.map((stage) => (
                <li
                  key={stage.id}
                  data-status={stage.status}
                  aria-current={current?.id === stage.id ? 'step' : undefined}
                >
                  <span>{stage.name}</span>
                  <small>
                    {stage.status === 'completed'
                      ? 'Завершён'
                      : current?.id === stage.id
                        ? 'Текущий этап'
                        : 'По плану'}
                  </small>
                </li>
              ))}
            </ol>
          ) : (
            <p>Руководитель ещё не добавил этапы.</p>
          ))}
      </section>
      {stages && <RecentRemarks thesisId={thesis.id} stages={stages} />}
      {Boolean(deadlines?.length) && (
        <section className={s.block}>
          <h2>Ближайшие сроки</h2>
          <ul className={s.rows}>
            {deadlines?.map((stage) => (
              <li key={stage.id}>
                <span>{stage.name}</span>
                <time dateTime={stage.due_date}>{date(stage.due_date)}</time>
              </li>
            ))}
          </ul>
        </section>
      )}
    </>
  )
}
