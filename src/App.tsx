import { useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Link,
  Navigate,
  NavLink,
  Outlet,
  Route,
  Routes,
  useNavigate,
} from 'react-router-dom'
import { AuthPage } from './features/auth/AuthPage'
import { GroupPage, Groups, Templates } from './features/groups/Groups'
import { VersionPage } from './features/review/VersionPage'
import { ThesisList } from './features/theses/ThesisList'
import { ThesisPage } from './features/theses/ThesisPage'
import { ApiError, send } from './shared/api/client'
import { useApi } from './shared/api/queries'
import type { User } from './shared/api/types'
import { Button, ErrorNotice, Notice } from './shared/ui/Ui'
import styles from './App.module.css'

function Shell({ user }: { user: User }) {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const logout = useMutation({
    mutationFn: () => send('/auth/logout', { method: 'POST' }),
    onSuccess: () => {
      queryClient.removeQueries({
        predicate: ({ queryKey }) => queryKey[0] !== '/auth/me',
      })
      queryClient.setQueryData(['/auth/me'], null)
      void navigate('/login', { replace: true })
    },
  })
  const student = user.role === 'student'
  return (
    <div className={styles.shell}>
      <a className={styles.skip} href="#content">
        К содержанию
      </a>
      <aside className={styles.rail}>
        <Link className={styles.brand} to="/">
          <span aria-hidden="true" className={styles.mark}>
            <span />
            <span />
            <span />
          </span>
          Норма
        </Link>
        <nav aria-label="Кабинет">
          {!student && (
            <NavLink className={styles.navItem} to="/groups">
              Группы
            </NavLink>
          )}
          <NavLink className={styles.navItem} to="/works">
            {student ? 'Моя ВКР' : 'Выпускные работы'}
          </NavLink>
          {!student && (
            <NavLink className={styles.navItem} to="/templates">
              Шаблоны
            </NavLink>
          )}
        </nav>
        <div className={styles.identity}>
          <div>
            <p>{user.full_name}</p>
            <small>
              {student ? user.academic_group : 'Научный руководитель'}
            </small>
          </div>
          <Button
            variant="secondary"
            disabled={logout.isPending}
            onClick={() => logout.mutate()}
          >
            Выйти
          </Button>
          <ErrorNotice error={logout.error} />
        </div>
      </aside>
      <main id="content" tabIndex={-1} className={styles.main}>
        <Outlet />
      </main>
    </div>
  )
}

export default function App() {
  const session = useApi<User | null>('/auth/me')
  if (session.isPending)
    return (
      <main className={styles.center}>
        <Notice>Проверяем вход…</Notice>
      </main>
    )
  if (
    session.error &&
    !(session.error instanceof ApiError && session.error.status === 401)
  ) {
    return (
      <main className={styles.center}>
        <ErrorNotice error={session.error} />
        <Button onClick={() => void session.refetch()}>Повторить</Button>
      </main>
    )
  }
  const user = session.error ? null : session.data
  if (!user)
    return (
      <Routes>
        <Route path="/login" element={<AuthPage key="login" />} />
        <Route
          path="/register"
          element={<AuthPage key="register" register />}
        />
        <Route path="*" element={<Navigate to="/login" replace />} />
      </Routes>
    )
  const home = user.role === 'student' ? '/works' : '/groups'
  return (
    <Routes>
      <Route element={<Shell user={user} />}>
        <Route index element={<Navigate to={home} replace />} />
        {user.role === 'supervisor' && (
          <>
            <Route path="groups" element={<Groups />} />
            <Route path="groups/:groupId" element={<GroupPage />} />
            <Route path="templates" element={<Templates />} />
          </>
        )}
        <Route path="works" element={<ThesisList role={user.role} />} />
        <Route
          path="works/:thesisId"
          element={<ThesisPage role={user.role} />}
        />
        <Route
          path="works/:thesisId/versions/:versionId"
          element={<VersionPage role={user.role} />}
        />
        <Route path="*" element={<Navigate to={home} replace />} />
      </Route>
    </Routes>
  )
}
