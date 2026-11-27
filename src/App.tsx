import { useMutation, useQueryClient } from '@tanstack/react-query'
import { lazy, Suspense } from 'react'
import {
  Link,
  Navigate,
  NavLink,
  Outlet,
  Route,
  Routes,
  useNavigate,
} from 'react-router-dom'
import { StudentHeader } from './features/profile/StudentHeader'
import { ProfilePage } from './features/profile/ProfilePage'
import { StudentMaterials } from './features/formatting/StudentMaterials'
import { AuthPage } from './features/auth/AuthPage'
import { GroupPage, Groups, Templates } from './features/groups/Groups'
import { VersionPage } from './features/review/VersionPage'
import { StudentHome, ThesisList } from './features/theses/ThesisList'
import { ThesisPage } from './features/theses/ThesisPage'
import { ApiError, send } from './shared/api/client'
import { useApi } from './shared/api/queries'
import type { User } from './shared/api/types'
import { Button, ErrorNotice, Notice } from './shared/ui/Ui'
import { Wordmark } from './shared/ui/Wordmark'
import styles from './App.module.css'

const DocumentEditor = lazy(
  () => import('./features/document-editor/DocumentEditor'),
)

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
      {student ? (
        <StudentHeader
          user={user}
          logout={() => logout.mutate()}
          pending={logout.isPending}
        />
      ) : (
        <header className={styles.header}>
          <div className={styles.headerInner}>
            <Link className={styles.brand} to="/">
              <Wordmark />
            </Link>
            <div className={styles.identity}>
              <div>
                <p>{user.full_name}</p>
                <small>Научный руководитель</small>
              </div>
              <Button
                variant="secondary"
                disabled={logout.isPending}
                onClick={() => logout.mutate()}
              >
                Выйти
              </Button>
            </div>
          </div>
          <nav className={styles.nav} aria-label="Кабинет руководителя">
            <NavLink className={styles.navItem} to="/groups">
              Группы
            </NavLink>
            <NavLink className={styles.navItem} to="/works">
              Выпускные работы
            </NavLink>
            <NavLink className={styles.navItem} to="/templates">
              Шаблоны
            </NavLink>
          </nav>
        </header>
      )}
      {logout.error && (
        <div className={styles.logoutError}>
          <ErrorNotice error={logout.error} />
        </div>
      )}
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
        <Route
          path="works"
          element={user.role === 'student' ? <StudentHome /> : <ThesisList />}
        />
        <Route
          path="works/:thesisId"
          element={<ThesisPage role={user.role} />}
        />
        {user.role === 'student' && (
          <>
            <Route path="profile" element={<ProfilePage user={user} />} />
            <Route path="profile/:tab" element={<ProfilePage user={user} />} />
            <Route path="materials" element={<StudentMaterials />} />
            <Route
              path="works/:thesisId/reviews"
              element={<ThesisPage role="student" reviews />}
            />
          </>
        )}
        <Route
          path="works/:thesisId/versions/:versionId"
          element={<VersionPage role={user.role} />}
        />
        <Route path="*" element={<Navigate to={home} replace />} />
      </Route>
      {user.role === 'student' && (
        <Route
          path="works/:thesisId/edit"
          element={
            <main className={styles.main}>
              <Suspense fallback={<Notice>Открываем редактор…</Notice>}>
                <DocumentEditor userId={user.id} />
              </Suspense>
            </main>
          }
        />
      )}
    </Routes>
  )
}
