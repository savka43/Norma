import { useForm } from '@tanstack/react-form'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { send } from '../../shared/api/client'
import type { User } from '../../shared/api/types'
import { Button, ErrorNotice, Field, Notice } from '../../shared/ui/Ui'
import styles from './AuthPage.module.css'

export function AuthPage({ register = false }: { register?: boolean }) {
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
      full_name: '',
      academic_group: '',
    },
    onSubmit: ({ value }) => mutation.mutateAsync(value).catch(() => undefined),
  })
  return (
    <main className={styles.layout}>
      <div className={styles.intro}>
        <div className={styles.brand}>Норма</div>
        <h1>Работа над ВКР</h1>
        <p>Этапы, сроки и замечания в одном кабинете.</p>
      </div>
      <section className={styles.side} aria-labelledby="auth-heading">
        <h2 id="auth-heading">
          {register ? 'Регистрация студента' : 'Вход в кабинет'}
        </h2>
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
              <form.Field name="full_name">
                {(field) => (
                  <Field
                    label="Имя и фамилия"
                    autoComplete="name"
                    required
                    maxLength={255}
                    value={field.state.value}
                    onChange={(event) => field.handleChange(event.target.value)}
                  />
                )}
              </form.Field>
              <form.Field name="academic_group">
                {(field) => (
                  <Field
                    label="Учебная группа"
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
                type="password"
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
          <ErrorNotice error={mutation.error} />
          <Button type="submit" disabled={mutation.isPending}>
            {register ? 'Создать аккаунт' : 'Войти'}
          </Button>
        </form>
        <Link to={register ? '/login' : '/register'}>
          {register ? 'Вернуться ко входу' : 'Зарегистрироваться студенту'}
        </Link>
      </section>
    </main>
  )
}
