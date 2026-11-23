import { useForm } from '@tanstack/react-form'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ApiError, send } from '../../shared/api/client'
import { invalidatePaths, useApi } from '../../shared/api/queries'
import type {
  Document,
  Stage,
  StageHistory,
  StagePlan,
  Thesis,
  User,
} from '../../shared/api/types'
import {
  Button,
  Chip,
  date,
  ErrorNotice,
  Field,
  Notice,
  Pager,
  Panel,
} from '../../shared/ui/Ui'
import w from '../../shared/ui/Workspace.module.css'
import { DocumentPanel } from './DocumentPanel'
import { getDocument, withLease } from './documents'
import { Progress } from './ThesisList'

const statuses = {
  in_progress: ['В работе', 'neutral'],
  in_review: ['На проверке', 'blue'],
  changes_requested: ['Нужны правки', 'orange'],
  completed: ['Подтверждён', 'green'],
} as const

const events: Record<string, string> = {
  created: 'Этап создан',
  updated: 'План изменён',
  submitted: 'Отправлен на проверку',
  changes_requested: 'Возвращён на доработку',
  confirmed: 'Этап подтверждён',
  resumed: 'Возвращён в работу',
}

export function useDocument(thesisId: string, enabled: boolean) {
  return useQuery({
    queryKey: [`/theses/${thesisId}/document`],
    queryFn: ({ signal }) => getDocument(thesisId, signal),
    enabled,
  })
}

function StageForm({
  thesis,
  plan,
  stage,
  onSaved,
}: {
  thesis: Thesis
  plan: StagePlan
  stage?: Stage
  onSaved?: () => void
}) {
  const client = useQueryClient()
  const max = plan.items.length + Number(!stage)
  const mutation = useMutation({
    mutationFn: (value: { name: string; position: number; due_date: string }) =>
      send<StagePlan>(
        stage ? `/stages/${stage.id}` : `/theses/${thesis.id}/stages`,
        {
          method: stage ? 'PATCH' : 'POST',
          json: { ...value, expected_revision: plan.revision },
        },
      ),
    onSuccess: (updated) => {
      client.setQueryData([`/theses/${thesis.id}/stages`], updated)
      onSaved?.()
      return invalidatePaths(client, '/theses', '/supervisor-groups', '/stages')
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status === 409)
        void invalidatePaths(client, `/theses/${thesis.id}/stages`)
    },
  })
  const form = useForm({
    defaultValues: {
      name: stage?.name ?? '',
      position: stage?.position ?? max,
      due_date: stage?.due_date ?? thesis.due_date,
    },
    onSubmit: async ({ value, formApi }) => {
      try {
        const updated = await mutation.mutateAsync(value)
        if (!stage)
          formApi.reset({
            name: '',
            position: updated.items.length + 1,
            due_date: thesis.due_date,
          })
      } catch {
        // The failed form remains editable.
      }
    },
  })
  return (
    <form
      className={w.form}
      onSubmit={(event) => {
        event.preventDefault()
        void form.handleSubmit()
      }}
    >
      <form.Field name="name">
        {(field) => (
          <Field
            label="Название этапа"
            required
            maxLength={255}
            value={field.state.value}
            onChange={(event) => field.handleChange(event.target.value)}
          />
        )}
      </form.Field>
      <div className={w.pair}>
        <form.Field name="due_date">
          {(field) => (
            <Field
              label="Срок этапа"
              type="date"
              required
              min={thesis.start_date}
              max={thesis.due_date}
              value={field.state.value}
              onChange={(event) => field.handleChange(event.target.value)}
            />
          )}
        </form.Field>
        <form.Field name="position">
          {(field) => (
            <Field
              label="Порядок"
              type="number"
              min={1}
              max={max}
              required
              value={field.state.value || ''}
              onChange={(event) =>
                field.handleChange(Number(event.target.value))
              }
            />
          )}
        </form.Field>
      </div>
      <ErrorNotice error={mutation.error} />
      <Button type="submit" disabled={mutation.isPending}>
        {stage ? 'Сохранить этап' : 'Добавить этап'}
      </Button>
    </form>
  )
}

function History({ stage, open }: { stage: Stage; open: boolean }) {
  const [offset, setOffset] = useState(0)
  const limit = 12
  const history = useApi<StageHistory>(
    `/stages/${stage.id}/history?limit=${limit}&offset=${offset}`,
    open,
  )
  if (!open) return null
  return (
    <div>
      <ErrorNotice error={history.error} />
      {history.isPending && <Notice>Загружаем историю…</Notice>}
      {history.data && (
        <>
          <ul className={w.list}>
            {history.data.items.map((event) => (
              <li key={event.id}>
                <div>
                  {events[event.kind] ?? event.kind} ·{' '}
                  <small>{date(event.created_at)}</small>
                </div>
                {event.reason && <p>{event.reason}</p>}
                {event.version_id && (
                  <Link
                    to={`/works/${stage.thesis_id}/versions/${event.version_id}`}
                  >
                    Версия события
                  </Link>
                )}
              </li>
            ))}
          </ul>
          <Pager
            offset={offset}
            limit={limit}
            size={history.data.items.length}
            onChange={setOffset}
          />
        </>
      )}
    </div>
  )
}

function StageRow({
  thesis,
  stage,
  plan,
  canPlan,
  student,
  document,
}: {
  thesis: Thesis
  stage: Stage
  plan: StagePlan
  canPlan: boolean
  student: boolean
  document: Document | null
}) {
  const client = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [historyOpen, setHistoryOpen] = useState(false)
  const mutation = useMutation({
    mutationFn: (
      input:
        | { action: 'submit'; document: Document }
        | { action: 'resume'; version: string },
    ) => {
      if (input.action === 'resume')
        return send(`/stages/${stage.id}/resume`, {
          method: 'POST',
          json: {
            expected_revision: plan.revision,
            submitted_version_id: input.version,
          },
        })
      const doc = input.document
      return withLease(doc.id, (headers) =>
        send(`/stages/${stage.id}/submit`, {
          method: 'POST',
          headers,
          json: {
            expected_revision: plan.revision,
            expected_document_revision: doc.revision,
          },
        }),
      )
    },
    onSettled: () =>
      invalidatePaths(
        client,
        '/theses',
        '/stages',
        ...(document ? [`/documents/${document.id}/versions`] : []),
      ),
  })
  const [label, tone] = statuses[stage.status]
  const maySubmit =
    student &&
    (stage.status === 'in_progress' || stage.status === 'changes_requested')
  const ready = document && document.last_version_number > 0
  return (
    <li>
      <div className={w.row}>
        <h3>
          {stage.position}. {stage.name}
        </h3>
        <Chip tone={tone}>{label}</Chip>
      </div>
      <p className={w.muted}>
        До {date(stage.due_date)}
        {stage.is_overdue ? ' · Просрочено' : ''}
      </p>
      <div className={w.actions}>
        {stage.submitted_version_id && (
          <Link
            to={`/works/${thesis.id}/versions/${stage.submitted_version_id}?stage=${stage.id}`}
          >
            {stage.status === 'in_review' && !student
              ? 'Открыть проверку'
              : 'Открыть отправленную версию'}
          </Link>
        )}
        {maySubmit && (
          <Button
            variant="secondary"
            disabled={!ready || mutation.isPending}
            onClick={() => {
              if (document) mutation.mutate({ action: 'submit', document })
            }}
          >
            Отправить на проверку
          </Button>
        )}
        {student &&
          stage.status === 'changes_requested' &&
          stage.submitted_version_id && (
            <Button
              variant="quiet"
              disabled={mutation.isPending}
              onClick={() => {
                if (stage.submitted_version_id)
                  mutation.mutate({
                    action: 'resume',
                    version: stage.submitted_version_id,
                  })
              }}
            >
              Вернуть в работу
            </Button>
          )}
        {canPlan && (
          <Button
            variant="quiet"
            aria-expanded={editing}
            onClick={() => setEditing(!editing)}
          >
            {editing ? 'Отменить правку' : 'Изменить этап'}
          </Button>
        )}
        <Button
          variant="quiet"
          aria-expanded={historyOpen}
          onClick={() => setHistoryOpen(!historyOpen)}
        >
          История
        </Button>
      </div>
      {maySubmit && !ready && (
        <small className={w.muted}>Загрузите DOCX, чтобы отправить этап.</small>
      )}
      <ErrorNotice error={mutation.error} />
      {canPlan && editing && (
        <StageForm
          key={`${stage.id}:${stage.name}:${stage.position}:${stage.due_date}`}
          thesis={thesis}
          stage={stage}
          plan={plan}
          onSaved={() => setEditing(false)}
        />
      )}
      <History stage={stage} open={historyOpen} />
    </li>
  )
}

export function ThesisPage({ role }: { role: User['role'] }) {
  const { thesisId = '' } = useParams()
  return <ThesisDetail key={thesisId} thesisId={thesisId} role={role} />
}

function ThesisDetail({
  thesisId,
  role,
}: {
  thesisId: string
  role: User['role']
}) {
  const thesis = useApi<Thesis>(`/theses/${thesisId}`)
  const plan = useApi<StagePlan>(`/theses/${thesisId}/stages`, !!thesis.data)
  const doc = useDocument(thesisId, !!thesis.data)
  const student = role === 'student'
  const locked =
    plan.data?.items.some((stage) => stage.status === 'in_review') ?? false
  const canPlan =
    !student &&
    !locked &&
    !plan.data?.items.some((stage) => stage.status === 'completed')
  return (
    <div className={w.page}>
      <header className={w.heading}>
        <div>
          <Link to="/works">{student ? 'Моя ВКР' : 'Выпускные работы'}</Link>
          <h1>{thesis.data?.title ?? 'Выпускная работа'}</h1>
          {thesis.data && (
            <p className={w.subheading}>
              {date(thesis.data.start_date)} — {date(thesis.data.due_date)}
            </p>
          )}
        </div>
        {thesis.data && <Progress thesis={thesis.data} />}
      </header>
      <ErrorNotice error={thesis.error} />
      {thesis.isPending && <Notice>Загружаем ВКР…</Notice>}
      {thesis.data && (
        <div className={w.columns}>
          <div className={w.stack}>
            <Panel title="Этапы ВКР">
              <ErrorNotice error={plan.error} />
              {plan.isPending && <Notice>Загружаем этапы…</Notice>}
              {plan.data && (
                <>
                  {!plan.data.items.length && (
                    <p>
                      {student
                        ? 'Руководитель ещё не добавил этапы.'
                        : 'Добавьте первый обязательный этап.'}
                    </p>
                  )}
                  <ol className={w.timeline}>
                    {plan.data.items.map((stage) => (
                      <StageRow
                        key={stage.id}
                        stage={stage}
                        thesis={thesis.data}
                        plan={plan.data}
                        canPlan={canPlan}
                        student={student}
                        document={doc.data ?? null}
                      />
                    ))}
                  </ol>
                  {!student && !canPlan && (
                    <p className={w.muted}>
                      План закреплён, пока есть этапы на проверке или
                      завершённые этапы.
                    </p>
                  )}
                </>
              )}
            </Panel>
            {canPlan && plan.data && (
              <Panel title="Новый этап">
                <StageForm thesis={thesis.data} plan={plan.data} />
              </Panel>
            )}
          </div>
          <div className={w.stack}>
            <ErrorNotice error={doc.error} />
            {doc.isPending && <Notice>Загружаем документ…</Notice>}
            {doc.data !== undefined && (
              <DocumentPanel
                thesisId={thesisId}
                document={doc.data}
                canEdit={student}
                locked={locked || !plan.data}
              />
            )}
          </div>
        </div>
      )}
    </div>
  )
}
