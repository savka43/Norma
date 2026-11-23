import { useId } from 'react'
import type {
  ButtonHTMLAttributes,
  InputHTMLAttributes,
  ReactNode,
} from 'react'
import styles from './Ui.module.css'

export function Button({
  variant = 'primary',
  className = '',
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'primary' | 'secondary' | 'quiet'
}) {
  return (
    <button
      type="button"
      {...props}
      className={`${styles.button} ${styles[variant]} ${className}`}
    />
  )
}

export function Field({
  label,
  hint,
  ...props
}: InputHTMLAttributes<HTMLInputElement> & { label: string; hint?: string }) {
  const id = useId()
  return (
    <label className={styles.field} htmlFor={id}>
      <span>{label}</span>
      <input
        {...props}
        id={id}
        aria-describedby={hint ? `${id}-hint` : undefined}
      />
      {hint && <small id={`${id}-hint`}>{hint}</small>}
    </label>
  )
}

export function Notice({
  children,
  error = false,
}: {
  children: ReactNode
  error?: boolean
}) {
  return (
    <p
      className={`${styles.notice} ${error ? styles.error : ''}`}
      role={error ? 'alert' : 'status'}
    >
      {children}
    </p>
  )
}

export function ErrorNotice({ error }: { error: unknown }) {
  return error ? (
    <Notice error>
      {error instanceof Error ? error.message : 'Действие не выполнено.'}
    </Notice>
  ) : null
}

export function Panel({
  title,
  action,
  children,
}: {
  title: string
  action?: ReactNode
  children: ReactNode
}) {
  return (
    <section className={styles.panel}>
      <div className={styles.panelHeader}>
        <h2>{title}</h2>
        {action}
      </div>
      <div className={styles.panelBody}>{children}</div>
    </section>
  )
}

export function Chip({
  tone = 'neutral',
  children,
}: {
  tone?: 'neutral' | 'blue' | 'orange' | 'green'
  children: ReactNode
}) {
  return <span className={`${styles.chip} ${styles[tone]}`}>{children}</span>
}

export function Pager({
  offset,
  limit,
  size,
  onChange,
}: {
  offset: number
  limit: number
  size: number
  onChange: (offset: number) => void
}) {
  if (!offset && size < limit) return null
  return (
    <nav className={styles.pager} aria-label="Страницы списка">
      <Button
        variant="secondary"
        disabled={!offset}
        onClick={() => onChange(Math.max(0, offset - limit))}
      >
        Назад
      </Button>
      <span>Страница {Math.floor(offset / limit) + 1}</span>
      <Button
        variant="secondary"
        disabled={size < limit}
        onClick={() => onChange(offset + limit)}
      >
        Дальше
      </Button>
    </nav>
  )
}

export const date = (value: string) =>
  new Intl.DateTimeFormat('ru-RU', {
    day: 'numeric',
    month: 'long',
    year: 'numeric',
    timeZone: 'UTC',
  }).format(new Date(value))
