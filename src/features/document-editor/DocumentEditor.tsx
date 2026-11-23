import { ListItemNode, ListNode } from '@lexical/list'
import { LexicalComposer } from '@lexical/react/LexicalComposer'
import { useLexicalComposerContext } from '@lexical/react/LexicalComposerContext'
import { HistoryPlugin } from '@lexical/react/LexicalHistoryPlugin'
import { ListPlugin } from '@lexical/react/LexicalListPlugin'
import { TablePlugin } from '@lexical/react/LexicalTablePlugin'
import { HeadingNode, QuoteNode } from '@lexical/rich-text'
import { TableCellNode, TableNode, TableRowNode } from '@lexical/table'
import {
  $getSelection,
  $isRangeSelection,
  COMMAND_PRIORITY_HIGH,
  PASTE_COMMAND,
} from 'lexical'
import { useEffect, useEffectEvent, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useApi } from '../../shared/api/queries'
import type {
  Document,
  StagePlan,
  TemplateVersion,
  Thesis,
  Version,
} from '../../shared/api/types'
import { Button, ErrorNotice, Notice } from '../../shared/ui/Ui'
import { useDocument } from '../theses/ThesisPage'
import styles from './DocumentEditor.module.css'
import { CaptionNode, ImageDocument, ImageNode } from './nodes'
import { Paper } from './Paper'
import {
  retainOriginalBlocks,
  serializeContent,
  type EditorContent,
} from './serialization'
import { Toolbar } from './Toolbar'
import {
  clearLocalDraft,
  draftKey,
  readLocalDraft,
  useEditing,
} from './useEditing'

const nodes = [
  HeadingNode,
  QuoteNode,
  ListNode,
  ListItemNode,
  TableNode,
  TableRowNode,
  TableCellNode,
  ImageNode,
  CaptionNode,
]

function EditPlugin({
  editable,
  initial,
  onChange,
}: {
  editable: boolean
  initial: EditorContent
  onChange: (draft: EditorContent) => void
}) {
  const [editor] = useLexicalComposerContext()
  const changed = useEffectEvent(onChange)

  useEffect(() => {
    editor.setEditable(editable)
  }, [editable, editor])

  useEffect(() => {
    const baseline = retainOriginalBlocks(editor.getEditorState(), initial)
    return editor.registerUpdateListener(
      ({ editorState, dirtyElements, dirtyLeaves }) => {
        if (editor.isEditable() && (dirtyElements.size || dirtyLeaves.size)) {
          changed(serializeContent(editorState, initial, baseline))
        }
      },
    )
  }, [editor, initial])

  useEffect(
    () =>
      editor.registerCommand(
        PASTE_COMMAND,
        (event) => {
          if (!(event instanceof ClipboardEvent) || !event.clipboardData)
            return false
          const clipboard = event.clipboardData
          if (clipboard.types.includes('application/x-lexical-editor'))
            return false
          const selection = $getSelection()
          if (!$isRangeSelection(selection)) return false
          event.preventDefault()
          selection.insertRawText(clipboard.getData('text/plain'))
          return true
        },
        COMMAND_PRIORITY_HIGH,
      ),
    [editor],
  )

  return null
}

function downloadDraft(content: EditorContent) {
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(content, null, 2)], { type: 'application/json' }),
  )
  const link = window.document.createElement('a')
  link.href = url
  link.download = 'Черновик ВКР.json'
  link.click()
  window.setTimeout(() => URL.revokeObjectURL(url), 0)
}

function Workspace({
  document,
  thesis,
  template,
  storageKey,
  wholeReview,
}: {
  document: Document
  thesis: Thesis
  template: TemplateVersion
  storageKey: string
  wholeReview: boolean
}) {
  const [localDraft] = useState(() => readLocalDraft(storageKey))
  const [staleDraft, setStaleDraft] = useState(() =>
    localDraft && localDraft.baseRevision !== document.revision
      ? localDraft
      : null,
  )
  const [source, setSource] = useState(() =>
    staleDraft ? document.content : (localDraft?.content ?? document.content),
  )
  const [editorKey, setEditorKey] = useState(0)
  const [version, setVersion] = useState<Version | null>(null)
  const [actionError, setActionError] = useState<unknown>(null)
  const [creatingVersion, setCreatingVersion] = useState(false)
  const [editorError, setEditorError] = useState<unknown>(null)
  const allowed = !wholeReview && !staleDraft
  const editing = useEditing(
    document,
    storageKey,
    staleDraft ? null : (localDraft?.content ?? null),
    allowed,
  )
  const editable = allowed && !!editing.lease
  const status = wholeReview
    ? 'Документ на проверке'
    : staleDraft
      ? 'Нужно восстановить черновик'
      : {
          opening: 'Открываем редактирование…',
          ready: editing.dirty ? 'Есть изменения' : 'Сохранено',
          saving: 'Сохраняем…',
          retry: 'Не удалось сохранить',
          conflict: editing.lease
            ? 'Сохранение приостановлено'
            : 'Редактирование недоступно',
        }[editing.status]

  async function snapshot() {
    setActionError(null)
    setCreatingVersion(true)
    try {
      const saved = await editing.createVersion()
      if (saved) setVersion(saved)
    } catch (failure) {
      setActionError(failure)
    } finally {
      setCreatingVersion(false)
    }
  }

  return (
    <div className={styles.workspace}>
      <header className={styles.heading}>
        <div>
          <Link to={`/works/${thesis.id}`}>К работе</Link>
          <h1>{thesis.title}</h1>
        </div>
        <div className={styles.saveControls}>
          <span className={styles.saveState} role="status">
            {status}
          </span>
          <Button
            variant="secondary"
            disabled={
              !editable || !editing.dirty || editing.status === 'saving'
            }
            onClick={() => void editing.save()}
          >
            Сохранить
          </Button>
          <Button
            variant="secondary"
            disabled={!editable || creatingVersion}
            onClick={() => void snapshot()}
          >
            Сохранить версию
          </Button>
        </div>
      </header>
      <ErrorNotice error={editing.error ?? actionError ?? editorError} />
      {wholeReview && (
        <Notice>
          На проверку отправлен весь документ. Редактирование станет доступно
          после решения руководителя.
        </Notice>
      )}
      {staleDraft && (
        <div className={styles.workspace}>
          <Notice>
            На устройстве есть черновик от более ранней редакции. Восстановление
            заменит текущий текст черновиком при сохранении.
          </Notice>
          <div className={styles.controls}>
            <Button
              disabled={wholeReview}
              onClick={() => {
                setSource(staleDraft.content)
                setEditorKey((key) => key + 1)
                editing.update(staleDraft.content)
                setStaleDraft(null)
              }}
            >
              Восстановить черновик
            </Button>
            <Button
              variant="secondary"
              onClick={() => downloadDraft(staleDraft.content)}
            >
              Скачать черновик
            </Button>
            <Button
              variant="secondary"
              onClick={() => {
                clearLocalDraft(storageKey)
                setStaleDraft(null)
              }}
            >
              Оставить серверный текст
            </Button>
          </div>
        </div>
      )}
      {(editing.status === 'conflict' || editing.status === 'retry') &&
        allowed && (
          <div className={styles.controls}>
            {!editing.lease && (
              <Button
                variant="secondary"
                onClick={() => void editing.acquire()}
              >
                Получить доступ
              </Button>
            )}
            <Button
              variant="secondary"
              onClick={() => window.location.reload()}
            >
              Перечитать с сервера
            </Button>
          </div>
        )}
      {editing.storageFailed && (
        <Notice error>
          Браузер не сохранил черновик на устройстве. Оставьте редактор открытым
          до успешного сохранения.
        </Notice>
      )}
      {version && (
        <Notice>
          Создана{' '}
          <Link to={`/works/${thesis.id}/versions/${version.id}`}>
            версия №{version.number}
          </Link>
          .
        </Notice>
      )}
      <ImageDocument.Provider value={document.id}>
        <LexicalComposer
          key={editorKey}
          initialConfig={{
            namespace: `norma-${document.id}`,
            nodes,
            editable: false,
            editorState: JSON.stringify(source),
            onError: setEditorError,
          }}
        >
          <HistoryPlugin />
          <ListPlugin />
          <TablePlugin hasCellBackgroundColor={false} />
          <EditPlugin
            editable={editable}
            initial={source}
            onChange={editing.update}
          />
          <Toolbar disabled={!editable} upload={editing.uploadImage} />
          <Paper parameters={template.parameters} />
        </LexicalComposer>
      </ImageDocument.Provider>
    </div>
  )
}

export default function DocumentEditor({ userId }: { userId: string }) {
  const { thesisId = '' } = useParams()
  const thesis = useApi<Thesis>(`/theses/${thesisId}`)
  const document = useDocument(thesisId, !!thesis.data)
  const plan = useApi<StagePlan>(`/theses/${thesisId}/stages`, !!thesis.data)
  const templateId = document.data?.template_version_id
  const template = useApi<TemplateVersion>(
    `/formatting-template-versions/${templateId}`,
    !!templateId,
  )
  const error = thesis.error ?? document.error ?? plan.error ?? template.error

  if (error) return <ErrorNotice error={error} />
  if (document.data === null)
    return (
      <Notice>
        Сначала создайте документ.{' '}
        <Link to={`/works/${thesisId}`}>К работе</Link>
      </Notice>
    )
  if (!thesis.data || !document.data || !template.data || !plan.data)
    return <Notice>Открываем документ…</Notice>

  const chapterIds = new Set(
    document.data.content.root.children.flatMap((block) =>
      block.type === 'heading' && block.$?.normaStageId
        ? [block.$.normaStageId]
        : [],
    ),
  )
  const wholeReview = plan.data.items.some(
    (stage) => stage.status === 'in_review' && !chapterIds.has(stage.id),
  )
  return (
    <Workspace
      key={document.data.id}
      document={document.data}
      thesis={thesis.data}
      template={template.data}
      storageKey={draftKey(userId, document.data.id)}
      wholeReview={wholeReview}
    />
  )
}
