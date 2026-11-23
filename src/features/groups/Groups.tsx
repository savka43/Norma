import { useForm } from '@tanstack/react-form'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { send } from '../../shared/api/client'
import { invalidatePaths, useApi } from '../../shared/api/queries'
import type {
  Group,
  GroupProgress,
  Page,
  Student,
  Template,
  TemplateCreated,
  TemplateParameters,
  Thesis,
} from '../../shared/api/types'
import {
  Button,
  date,
  ErrorNotice,
  Field,
  Notice,
  Pager,
  Panel,
} from '../../shared/ui/Ui'
import w from '../../shared/ui/Workspace.module.css'
import { Progress } from '../theses/ThesisList'

const limit = 25

export function Groups() {
  const [offset, setOffset] = useState(0)
  const groups = useApi<Page<Group>>(
    `/supervisor-groups?limit=${limit}&offset=${offset}`,
  )
  const client = useQueryClient()
  const navigate = useNavigate()
  const create = useMutation({
    mutationFn: (fields: { name: string; academic_year: number }) =>
      send<Group>('/supervisor-groups', { method: 'POST', json: fields }),
    onSuccess: (group) => {
      void invalidatePaths(client, '/supervisor-groups')
      void navigate(`/groups/${group.id}`)
    },
  })
  const form = useForm({
    defaultValues: { name: '', academic_year: new Date().getFullYear() },
    onSubmit: ({ value }) => create.mutateAsync(value).catch(() => undefined),
  })
  return (
    <div className={w.page}>
      <header className={w.heading}>
        <div>
          <p>Кабинет руководителя</p>
          <h1>Группы</h1>
        </div>
      </header>
      <div className={w.columns}>
        <Panel title="Мои группы">
          <ErrorNotice error={groups.error} />
          {groups.isPending && <Notice>Загружаем группы…</Notice>}
          {groups.data && (
            <>
              {!groups.data.items.length && <p>На этой странице нет групп.</p>}
              <ul className={w.list}>
                {groups.data.items.map((group) => (
                  <li key={group.id}>
                    <Link to={`/groups/${group.id}`}>{group.name}</Link>
                    <p className={w.muted}>
                      {group.academic_year} / {group.academic_year + 1}
                    </p>
                  </li>
                ))}
              </ul>
              <Pager
                limit={limit}
                offset={offset}
                size={groups.data.items.length}
                onChange={setOffset}
              />
            </>
          )}
        </Panel>
        <Panel title="Создать группу">
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
                  label="Название группы"
                  required
                  maxLength={255}
                  value={field.state.value}
                  onChange={(event) => field.handleChange(event.target.value)}
                />
              )}
            </form.Field>
            <form.Field name="academic_year">
              {(field) => (
                <Field
                  label="Начало учебного года"
                  type="number"
                  min={1}
                  max={9998}
                  required
                  value={field.state.value || ''}
                  onChange={(event) =>
                    field.handleChange(Number(event.target.value))
                  }
                />
              )}
            </form.Field>
            <ErrorNotice error={create.error} />
            <Button type="submit" disabled={create.isPending}>
              Создать группу
            </Button>
          </form>
        </Panel>
      </div>
    </div>
  )
}

function FindStudent({ groupId }: { groupId: string }) {
  const [search, setSearch] = useState({ query: '', offset: 0 })
  const limit = 12
  const key = `/students?query=${encodeURIComponent(search.query)}&limit=${limit}&offset=${search.offset}`
  const students = useApi<Page<Student>>(key, search.query.length >= 3)
  const client = useQueryClient()
  const add = useMutation({
    mutationFn: (student_id: string) =>
      send(`/supervisor-groups/${groupId}/students`, {
        method: 'POST',
        json: { student_id },
      }),
    onSuccess: () =>
      invalidatePaths(client, '/students', `/supervisor-groups/${groupId}`),
  })
  const form = useForm({
    defaultValues: { query: '' },
    onSubmit: ({ value }) =>
      setSearch({ query: value.query.trim(), offset: 0 }),
  })
  return (
    <Panel title="Добавить студента">
      <form
        className={w.form}
        onSubmit={(event) => {
          event.preventDefault()
          void form.handleSubmit()
        }}
      >
        <form.Field name="query">
          {(field) => (
            <Field
              label="Имя или email"
              hint="От 3 символов"
              type="search"
              minLength={3}
              maxLength={100}
              required
              value={field.state.value}
              onChange={(event) => field.handleChange(event.target.value)}
            />
          )}
        </form.Field>
        <Button type="submit">Найти студента</Button>
      </form>
      <ErrorNotice error={students.error ?? add.error} />
      {search.query && search.query.length < 3 && (
        <Notice>Введите хотя бы три символа без пробелов по краям.</Notice>
      )}
      {students.isFetching && <Notice>Ищем студентов…</Notice>}
      {students.data && (
        <div className={w.stack}>
          {!students.data.items.length && (
            <p>Подходящих свободных студентов нет.</p>
          )}
          <ul className={w.list}>
            {students.data.items.map((student) => (
              <li className={w.row} key={student.id}>
                <div>
                  <strong>{student.full_name}</strong>
                  <p>{student.email}</p>
                  <small>{student.academic_group}</small>
                </div>
                <Button
                  variant="secondary"
                  disabled={add.isPending}
                  onClick={() => add.mutate(student.id)}
                >
                  Добавить
                </Button>
              </li>
            ))}
          </ul>
          <Pager
            offset={search.offset}
            limit={limit}
            size={students.data.items.length}
            onChange={(offset) => setSearch({ ...search, offset })}
          />
        </div>
      )}
    </Panel>
  )
}

function AssignThesis({ student }: { student: Student }) {
  const navigate = useNavigate()
  const client = useQueryClient()
  const create = useMutation({
    mutationFn: (value: {
      title: string
      start_date: string
      due_date: string
    }) =>
      send<Thesis>('/theses', {
        method: 'POST',
        json: { ...value, student_id: student.id },
      }),
    onSuccess: (thesis) => {
      void invalidatePaths(client, '/theses', '/supervisor-groups')
      void navigate(`/works/${thesis.id}`)
    },
  })
  const form = useForm({
    defaultValues: {
      title: '',
      start_date: new Date().toISOString().slice(0, 10),
      due_date: '',
    },
    onSubmit: ({ value }) => create.mutateAsync(value).catch(() => undefined),
  })
  return (
    <details>
      <summary className={w.toggle}>Назначить ВКР</summary>
      <form
        className={w.form}
        onSubmit={(event) => {
          event.preventDefault()
          void form.handleSubmit()
        }}
      >
        <form.Field name="title">
          {(field) => (
            <Field
              label="Тема ВКР"
              required
              maxLength={500}
              value={field.state.value}
              onChange={(event) => field.handleChange(event.target.value)}
            />
          )}
        </form.Field>
        <div className={w.pair}>
          <form.Field name="start_date">
            {(field) => (
              <Field
                label="Дата начала"
                type="date"
                required
                value={field.state.value}
                onChange={(event) => field.handleChange(event.target.value)}
              />
            )}
          </form.Field>
          <form.Field name="due_date">
            {(field) => (
              <Field
                label="Срок ВКР"
                type="date"
                required
                value={field.state.value}
                onChange={(event) => field.handleChange(event.target.value)}
              />
            )}
          </form.Field>
        </div>
        <ErrorNotice error={create.error} />
        <Button type="submit" disabled={create.isPending}>
          Создать ВКР
        </Button>
      </form>
    </details>
  )
}

export function GroupPage() {
  const { groupId = '' } = useParams()
  return <GroupDetail key={groupId} groupId={groupId} />
}

function GroupDetail({ groupId }: { groupId: string }) {
  const [offset, setOffset] = useState(0)
  const group = useApi<Group>(`/supervisor-groups/${groupId}`)
  const progress = useApi<GroupProgress>(
    `/supervisor-groups/${groupId}/progress?limit=${limit}&offset=${offset}`,
    !!group.data,
  )
  return (
    <div className={w.page}>
      <header className={w.heading}>
        <div>
          <Link to="/groups">Все группы</Link>
          <h1>{group.data?.name ?? 'Группа'}</h1>
          {group.data && (
            <p className={w.subheading}>
              {group.data.academic_year} / {group.data.academic_year + 1}
            </p>
          )}
        </div>
      </header>
      <ErrorNotice error={group.error} />
      {group.isPending && <Notice>Загружаем группу…</Notice>}
      {group.data && (
        <div className={w.columns}>
          <Panel title="Студенты и прогресс">
            <ErrorNotice error={progress.error} />
            {progress.isPending && <Notice>Загружаем состав группы…</Notice>}
            {progress.data && (
              <>
                {!progress.data.items.length && (
                  <p>
                    {offset
                      ? 'На этой странице нет студентов.'
                      : 'Добавьте зарегистрированного студента через поиск.'}
                  </p>
                )}
                <ul className={w.list}>
                  {progress.data.items.map(({ student, thesis, stages }) => (
                    <li key={student.id}>
                      <div className={w.row}>
                        <div>
                          <strong>{student.full_name}</strong>
                          <p className={w.muted}>{student.academic_group}</p>
                        </div>
                        {thesis && <Progress thesis={thesis} />}
                      </div>
                      {thesis ? (
                        <>
                          <Link to={`/works/${thesis.id}`}>{thesis.title}</Link>
                          <p className={w.muted}>
                            Срок: {date(thesis.due_date)}
                            {thesis.is_overdue ? ' · Просрочено' : ''}
                          </p>
                          {stages.some((stage) => stage.is_overdue) && (
                            <small>
                              Просроченные этапы:{' '}
                              {stages
                                .filter((stage) => stage.is_overdue)
                                .map((stage) => stage.name)
                                .join(', ')}
                            </small>
                          )}
                        </>
                      ) : (
                        <AssignThesis student={student} />
                      )}
                    </li>
                  ))}
                </ul>
                <Pager
                  limit={limit}
                  offset={offset}
                  size={progress.data.items.length}
                  onChange={setOffset}
                />
              </>
            )}
          </Panel>
          <FindStudent groupId={groupId} />
        </div>
      )}
    </div>
  )
}

export function Templates() {
  const [offset, setOffset] = useState(0)
  const templates = useApi<Page<Template>>(
    `/formatting-templates?limit=${limit}&offset=${offset}`,
  )
  const preset = useApi<TemplateParameters>(
    '/formatting-presets/gost-7-32-2017',
  )
  const client = useQueryClient()
  const create = useMutation({
    mutationFn: (name: string) =>
      send<TemplateCreated>('/formatting-templates', {
        method: 'POST',
        json: { name, parameters: preset.data },
      }),
    onSuccess: () => invalidatePaths(client, '/formatting-templates'),
  })
  const form = useForm({
    defaultValues: { name: 'ГОСТ 7.32-2017' },
    onSubmit: ({ value }) =>
      create.mutateAsync(value.name).catch(() => undefined),
  })
  return (
    <div className={w.page}>
      <header className={w.heading}>
        <div>
          <p>Кабинет руководителя</p>
          <h1>Шаблоны</h1>
        </div>
      </header>
      <div className={w.columns}>
        <Panel title="Доступные студентам">
          <ErrorNotice error={templates.error} />
          {templates.isPending && <Notice>Загружаем шаблоны…</Notice>}
          {templates.data && (
            <>
              {!templates.data.items.length && (
                <p>На этой странице нет шаблонов.</p>
              )}
              <ul className={w.list}>
                {templates.data.items.map((template) => (
                  <li key={template.id}>
                    {template.name}{' '}
                    <small className={w.muted}>
                      Версия {template.latest_version}
                    </small>
                  </li>
                ))}
              </ul>
              <Pager
                offset={offset}
                limit={limit}
                size={templates.data.items.length}
                onChange={setOffset}
              />
            </>
          )}
        </Panel>
        <Panel title="Добавить шаблон по ГОСТ">
          <form
            className={w.form}
            onSubmit={(event) => {
              event.preventDefault()
              if (preset.data) void form.handleSubmit()
            }}
          >
            <form.Field name="name">
              {(field) => (
                <Field
                  label="Название шаблона"
                  required
                  maxLength={255}
                  value={field.state.value}
                  onChange={(event) => field.handleChange(event.target.value)}
                />
              )}
            </form.Field>
            <ErrorNotice error={preset.error ?? create.error} />
            {create.isSuccess && (
              <Notice>Шаблон доступен студентам вашей группы.</Notice>
            )}
            <Button type="submit" disabled={!preset.data || create.isPending}>
              Добавить шаблон
            </Button>
          </form>
        </Panel>
      </div>
    </div>
  )
}
