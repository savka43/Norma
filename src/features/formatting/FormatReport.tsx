import { useMutation } from '@tanstack/react-query'
import { send } from '../../shared/api/client'
import type {
  FormattingReport,
  TextStyle,
  VersionSummary,
} from '../../shared/api/types'
import { Button, ErrorNotice, Notice } from '../../shared/ui/Ui'
import w from '../../shared/ui/Workspace.module.css'
import styles from './Formatting.module.css'
import { alignments } from './TemplateFields'

type Issue = FormattingReport['issues'][number]

function issueDescription(issue: Issue) {
  if (issue.code === 'indent_override') return 'Ручной отступ'
  if (issue.code === 'text_effect_override') return 'Ручной эффект текста'
  const expected = alignments[issue.expected as TextStyle['alignment']]
  return expected
    ? `Требуется выравнивание ${expected.toLowerCase()}`
    : 'Ручное выравнивание'
}

function location(path: string) {
  const indices = Array.from(
    path.matchAll(/children\[(\d+)\]/g),
    ([, index]) => Number(index) + 1,
  )
  return indices.length ? `Блок ${indices.join('.')}` : 'Документ'
}

export function FormatReport({ version }: { version: VersionSummary }) {
  const check = useMutation({
    mutationFn: () =>
      send<FormattingReport>(`/document-versions/${version.id}/format-check`, {
        method: 'POST',
      }),
  })
  const report = check.data

  return (
    <div className={w.stack}>
      <p className={w.muted}>
        Проверка ручного оформления в версии №{version.number} по её
        сохранённому шаблону.
      </p>
      <div>
        <Button
          variant="secondary"
          disabled={check.isPending}
          onClick={() => check.mutate()}
        >
          {check.isPending ? 'Проверяем оформление…' : 'Проверить оформление'}
        </Button>
      </div>
      <ErrorNotice error={check.error} />
      {report && (
        <div>
          <Notice>
            {report.conforms
              ? 'Ручных отклонений от шаблона нет.'
              : `Количество отклонений от шаблона: ${report.issue_count}.`}
          </Notice>
          {!!report.issues.length && (
            <>
              <ul
                className={`${styles.compactList} ${styles.report}`}
                tabIndex={0}
                aria-label="Отклонения от шаблона"
              >
                {report.issues.map((issue) => (
                  <li key={`${issue.path}:${issue.code}`}>
                    {location(issue.path)}. {issueDescription(issue)}
                  </li>
                ))}
              </ul>
              {report.truncated && (
                <p>Показаны первые {report.issues.length} отклонений.</p>
              )}
            </>
          )}
        </div>
      )}
    </div>
  )
}
