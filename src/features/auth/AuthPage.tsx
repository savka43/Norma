import { useForm } from '@tanstack/react-form'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { send } from '../../shared/api/client'
import type { User } from '../../shared/api/types'
import { Button, ErrorNotice, Field, Notice } from '../../shared/ui/Ui'
import { Wordmark } from '../../shared/ui/Wordmark'
import styles from './AuthPage.module.css'

export function AuthPage({ register = false }: { register?: boolean }) {
  const [visible, setVisible] = useState(false)
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const state = useLocation().state as { registeredEmail?: unknown } | null
  const registeredEmail =
    !register && typeof state?.registeredEmail === 'string'
      ? state.registeredEmail
      : ''
  const mutation = useMutation({
    gcTime: 0,
    mutationFn: async ({
      email,
      password,
      full_name,
      academic_group,
    }: {
      email: string
      password: string
      full_name: string
      academic_group: string
    }) => {
      if (register) {
        if (full_name.length > 255)
          throw new Error('Сократите ФИО до 255 символов.')
        await send('/auth/register', {
          method: 'POST',
          json: { email, password, full_name, academic_group },
        })
        return null
      }
      return send<User>('/auth/login', {
        method: 'POST',
        json: { email, password },
      })
    },
    onSuccess: (user, fields) => {
      if (!user) {
        void navigate('/login', {
          replace: true,
          state: { registeredEmail: fields.email },
        })
        return
      }
      queryClient.removeQueries({
        predicate: ({ queryKey }) => queryKey[0] !== '/auth/me',
      })
      queryClient.setQueryData(['/auth/me'], user)
      void navigate('/', { replace: true })
    },
  })
  const form = useForm({
    defaultValues: {
      email: registeredEmail,
      password: '',
      family: '',
      given: '',
      patronymic: '',
      confirmation: '',
      academic_group: '',
    },
    onSubmit: ({ value }) =>
      mutation
        .mutateAsync({
          email: value.email.trim(),
          password: value.password,
          full_name: [value.family, value.given, value.patronymic]
            .map((part) => part.trim())
            .filter(Boolean)
            .join(' '),
          academic_group: value.academic_group.trim(),
        })
        .catch(() => undefined),
  })
  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <Wordmark />
      </header>
      <main className={styles.layout} aria-labelledby="auth-heading">
        <h1 id="auth-heading">
          {register ? 'Регистрация студента' : 'Вход в кабинет'}
        </h1>
        {registeredEmail && (
          <Notice>Аккаунт создан. Введите пароль, чтобы войти.</Notice>
        )}
        <form
          className={styles.form}
          onSubmit={(event) => {
            event.preventDefault()
            void form.handleSubmit()
          }}
        >
          {register && (
            <>
              {(
                [
                  ['family', 'Фамилия', 'family-name'],
                  ['given', 'Имя', 'given-name'],
                  ['patronymic', 'Отчество (если есть)', 'additional-name'],
                ] as const
              ).map(([name, label, autoComplete]) => (
                <form.Field key={name} name={name}>
                  {(field) => (
                    <Field
                      label={label}
                      autoComplete={autoComplete}
                      required={name !== 'patronymic'}
                      pattern={'.*\\S.*'}
                      maxLength={255}
                      value={field.state.value}
                      onChange={(event) =>
                        field.handleChange(event.target.value)
                      }
                    />
                  )}
                </form.Field>
              ))}
              <form.Field name="academic_group">
                {(field) => (
                  <Field
                    label="Учебная группа"
                    pattern={'.*\\S.*'}
                    required
                    maxLength={100}
                    value={field.state.value}
                    onChange={(event) => field.handleChange(event.target.value)}
                  />
                )}
              </form.Field>
            </>
          )}
          <form.Field name="email">
            {(field) => (
              <Field
                label="Электронная почта"
                type="email"
                autoComplete="username"
                required
                maxLength={254}
                value={field.state.value}
                onChange={(event) => field.handleChange(event.target.value)}
              />
            )}
          </form.Field>
          <form.Field name="password">
            {(field) => (
              <Field
                label="Пароль"
                type={visible ? 'text' : 'password'}
                autoComplete={register ? 'new-password' : 'current-password'}
                required
                minLength={register ? 12 : 1}
                maxLength={128}
                hint={register ? 'От 12 символов' : undefined}
                value={field.state.value}
                onChange={(event) => field.handleChange(event.target.value)}
              />
            )}
          </form.Field>
          {register && (
            <form.Field
              name="confirmation"
              validators={{
                onChangeListenTo: ['password'],
                onChange: ({ value, fieldApi }) =>
                  value && value !== fieldApi.form.getFieldValue('password')
                    ? 'Пароли не совпадают.'
                    : undefined,
              }}
            >
              {(field) => {
                const error = field.state.meta.errors[0]
                return (
                  <Field
                    label="Повторите пароль"
                    type={visible ? 'text' : 'password'}
                    required
                    autoComplete="new-password"
                    value={field.state.value}
                    aria-invalid={Boolean(error)}
                    hint={error}
                    onChange={(event) => field.handleChange(event.target.value)}
                  />
                )
              }}
            </form.Field>
          )}
          <label className={styles.show}>
            <input
              type="checkbox"
              checked={visible}
              onChange={(event) => setVisible(event.target.checked)}
            />
            Показать пароль
          </label>
          <ErrorNotice error={mutation.error} />
          <Button type="submit" disabled={mutation.isPending}>
            {mutation.isPending
              ? register
                ? 'Создаём аккаунт…'
                : 'Входим…'
              : register
                ? 'Создать аккаунт'
                : 'Войти'}
          </Button>
        </form>
        {!register && (
          <details className={styles.recovery}>
            <summary>Забыли пароль?</summary>
            <p>Самостоятельное восстановление пароля пока недоступно.</p>
          </details>
        )}
        <div className={styles.alternate}>
          <Link to={register ? '/login' : '/register'}>
            {register ? 'Вернуться ко входу' : 'Зарегистрироваться студенту'}
          </Link>
        </div>
      </main>
    </div>
  )
}
