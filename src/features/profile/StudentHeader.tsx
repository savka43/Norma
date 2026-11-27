import { useEffect, useRef, type ReactNode } from 'react'
import { Link, NavLink, useLocation } from 'react-router-dom'
import { useApi } from '../../shared/api/queries'
import type { User, Page, Thesis } from '../../shared/api/types'
import { Wordmark } from '../../shared/ui/Wordmark'
import shell from '../../App.module.css'
import s from './Profile.module.css'

function HeaderMenu({
  label,
  trigger,
  children,
}: {
  label: string
  trigger: string
  children: ReactNode
}) {
  const details = useRef<HTMLDetailsElement>(null)
  useEffect(() => {
    function dismiss(event: PointerEvent) {
      if (details.current && !details.current.contains(event.target as Node))
        details.current.open = false
    }
    document.addEventListener('pointerdown', dismiss)
    return () => document.removeEventListener('pointerdown', dismiss)
  }, [])
  return (
    <details
      className={s.menu}
      ref={details}
      onKeyDown={(event) => {
        if (event.key === 'Escape' && details.current?.open) {
          details.current.open = false
          details.current.querySelector('summary')?.focus()
        }
      }}
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget))
          event.currentTarget.open = false
      }}
    >
      <summary aria-label={label} title={label}>
        {trigger}
      </summary>
      <div
        className={s.dropdown}
        onClick={(event) => {
          if ((event.target as HTMLElement).closest('a') && details.current) {
            details.current.open = false
            details.current.querySelector('summary')?.focus()
          }
        }}
      >
        {children}
      </div>
    </details>
  )
}

export function StudentHeader({
  user,
  logout,
  pending,
}: {
  user: User
  logout: () => void
  pending: boolean
}) {
  const { pathname } = useLocation()
  const assigned = useApi<Page<Thesis>>('/theses?limit=1')
  const work = assigned.data?.items[0]
  const base = work && '/works/' + work.id
  return (
    <header className={shell.header}>
      <div className={shell.headerInner}>
        <Link className={shell.brand} to="/works">
          <Wordmark />
        </Link>
        <nav className={shell.studentNav} aria-label="Кабинет студента">
          <Link
            className={shell.navItem}
            to="/works"
            aria-current={
              pathname === '/works' || pathname === base ? 'page' : undefined
            }
          >
            Моя ВКР
          </Link>
          {base ? (
            <>
              <NavLink className={shell.navItem} to={base + '/edit'}>
                Редактор
              </NavLink>
              <NavLink className={shell.navItem} to={base + '/reviews'}>
                Проверки
              </NavLink>
            </>
          ) : (
            <>
              <span
                className={shell.unavailable}
                title="Доступно после назначения ВКР"
              >
                Редактор
              </span>
              <span
                className={shell.unavailable}
                title="Доступно после назначения ВКР"
              >
                Проверки
              </span>
            </>
          )}
          <NavLink className={shell.navItem} to="/materials">
            Материалы
          </NavLink>
        </nav>
        <div className={shell.identity}>
          <HeaderMenu
            key={'notifications' + pathname}
            label="Уведомления"
            trigger="Уведомления"
          >
            <div className={s.account}>
              <strong>Уведомления</strong>
              <p>Лента событий пока не подключена.</p>
            </div>
            {base && <Link to={base + '/reviews'}>Посмотреть проверки</Link>}
            <Link to="/profile/notifications">Настройки уведомлений</Link>
          </HeaderMenu>
          <HeaderMenu
            key={'account' + pathname}
            label="Меню профиля"
            trigger={user.full_name
              .trim()
              .split(/\s+/)
              .slice(0, 2)
              .map((part) => part[0])
              .join('')
              .toLocaleUpperCase('ru')}
          >
            <div className={s.account}>
              <strong>{user.full_name}</strong>
              <small>
                {['Студент', user.academic_group].filter(Boolean).join(' · ')}
              </small>
              <small>{user.email}</small>
            </div>
            <Link to="/profile">Мой профиль</Link>
            <Link to="/profile/security">Настройки</Link>
            <button onClick={logout} disabled={pending}>
              Выйти
            </button>
          </HeaderMenu>
        </div>
      </div>
    </header>
  )
}
