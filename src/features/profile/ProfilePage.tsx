import { Navigate, NavLink, useParams } from 'react-router-dom'
import type { User } from '../../shared/api/types'
import s from './Profile.module.css'

const tabs = [
  ['', 'Личные данные'],
  ['security', 'Безопасность'],
  ['notifications', 'Уведомления'],
] as const

export function ProfilePage({ user }: { user: User }) {
  const { tab = '' } = useParams()
  if (!tabs.some(([path]) => path === tab))
    return <Navigate to="/profile" replace />
  return (
    <div className={s.page}>
      <h1>Мой профиль</h1>
      <nav className={s.tabs} aria-label="Разделы профиля">
        {tabs.map(([path, label]) => (
          <NavLink end key={path} to={path ? '/profile/' + path : '/profile'}>
            {label}
          </NavLink>
        ))}
      </nav>
      <section className={s.surface}>
        {tab === 'security' ? (
          <>
            <h2>Пароль</h2>
            <p>
              Самостоятельная смена и восстановление пароля пока недоступны.
            </p>
          </>
        ) : tab === 'notifications' ? (
          <>
            <h2>Уведомления по почте</h2>
            <p>
              Почтовая рассылка пока не подключена. Статусы этапов доступны в
              кабинете ВКР.
            </p>
          </>
        ) : (
          <>
            <h2>Данные учётной записи</h2>
            <dl className={s.facts}>
              {[
                ['ФИО', user.full_name],
                ['Электронная почта', user.email],
                ['Учебная группа', user.academic_group ?? 'Не указана'],
                ['Роль', 'Студент'],
              ].map(([label, value]) => (
                <div key={label}>
                  <dt>{label}</dt>
                  <dd>{value}</dd>
                </div>
              ))}
            </dl>
          </>
        )}
      </section>
    </div>
  )
}
