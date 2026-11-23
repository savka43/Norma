import {
  INSERT_ORDERED_LIST_COMMAND,
  INSERT_UNORDERED_LIST_COMMAND,
} from '@lexical/list'
import { useLexicalComposerContext } from '@lexical/react/LexicalComposerContext'
import { $createHeadingNode, type HeadingTagType } from '@lexical/rich-text'
import { $setBlocksType } from '@lexical/selection'
import { INSERT_TABLE_COMMAND } from '@lexical/table'
import {
  $createParagraphNode,
  $getSelection,
  $insertNodes,
  $isRangeSelection,
  $setSelection,
  FORMAT_TEXT_COMMAND,
  REDO_COMMAND,
  UNDO_COMMAND,
} from 'lexical'
import { useRef, useState } from 'react'
import { ErrorNotice } from '../../shared/ui/Ui'
import { CaptionNode, ImageNode } from './nodes'
import styles from './DocumentEditor.module.css'

const headings = ['h1', 'h2', 'h3', 'h4', 'h5', 'h6'] as const

export function Toolbar({
  disabled,
  upload,
}: {
  disabled: boolean
  upload: (file: File) => Promise<{ id: string } | null>
}) {
  const [editor] = useLexicalComposerContext()
  const fileInput = useRef<HTMLInputElement>(null)
  const selection = useRef<ReturnType<typeof $getSelection>>(null)
  const [error, setError] = useState<unknown>(null)
  const [uploading, setUploading] = useState(false)

  function blockStyle(style: string) {
    if (!style) return
    editor.update(() => {
      const current = $getSelection()
      if (!$isRangeSelection(current)) return
      $setBlocksType(current, () => {
        if (style === 'figure' || style === 'table')
          return new CaptionNode(style)
        if (style === 'paragraph') return $createParagraphNode()
        return $createHeadingNode(style as HeadingTagType)
      })
    })
    editor.focus()
  }

  async function insertImage(file: File) {
    setError(null)
    setUploading(true)
    try {
      const asset = await upload(file)
      if (!asset) return
      editor.update(() => {
        const previous = selection.current
        if (
          !$isRangeSelection($getSelection()) &&
          $isRangeSelection(previous)
        ) {
          $setSelection(previous)
        }
        $insertNodes([new ImageNode(asset.id, file.name.slice(0, 2000))])
      })
      editor.focus()
    } catch (failure) {
      setError(failure)
    } finally {
      setUploading(false)
    }
  }

  return (
    <>
      <div className={styles.toolbar} role="group" aria-label="Форматирование">
        <select
          aria-label="Стиль блока"
          value=""
          disabled={disabled}
          onChange={(event) => blockStyle(event.target.value)}
        >
          <option value="">Стиль блока</option>
          <option value="paragraph">Основной текст</option>
          {headings.map((tag, index) => (
            <option value={tag} key={tag}>
              Заголовок {index + 1}
            </option>
          ))}
          <option value="figure">Подпись рисунка</option>
          <option value="table">Подпись таблицы</option>
        </select>
        <div
          className={styles.toolGroup}
          onPointerDown={(event) => event.preventDefault()}
        >
          <button
            type="button"
            aria-label="Полужирный"
            disabled={disabled}
            onClick={() => editor.dispatchCommand(FORMAT_TEXT_COMMAND, 'bold')}
          >
            <b>Ж</b>
          </button>
          <button
            type="button"
            aria-label="Курсив"
            disabled={disabled}
            onClick={() =>
              editor.dispatchCommand(FORMAT_TEXT_COMMAND, 'italic')
            }
          >
            <i>К</i>
          </button>
        </div>
        <div
          className={styles.toolGroup}
          onPointerDown={(event) => event.preventDefault()}
        >
          <button
            type="button"
            aria-label="Маркированный список"
            disabled={disabled}
            onClick={() =>
              editor.dispatchCommand(INSERT_UNORDERED_LIST_COMMAND, undefined)
            }
          >
            • Список
          </button>
          <button
            type="button"
            aria-label="Нумерованный список"
            disabled={disabled}
            onClick={() =>
              editor.dispatchCommand(INSERT_ORDERED_LIST_COMMAND, undefined)
            }
          >
            1. Список
          </button>
        </div>
        <div
          className={styles.toolGroup}
          onPointerDown={(event) => event.preventDefault()}
        >
          <button
            type="button"
            disabled={disabled}
            onClick={() =>
              editor.dispatchCommand(INSERT_TABLE_COMMAND, {
                columns: '2',
                rows: '2',
                includeHeaders: true,
              })
            }
          >
            Таблица
          </button>
          <button
            type="button"
            disabled={disabled || uploading}
            onClick={() => {
              selection.current = editor
                .getEditorState()
                .read(() => $getSelection()?.clone() ?? null)
              fileInput.current?.click()
            }}
          >
            {uploading ? 'Загружаем…' : 'Изображение'}
          </button>
          <input
            type="file"
            accept="image/png,image/jpeg"
            hidden
            ref={fileInput}
            onChange={(event) => {
              const file = event.currentTarget.files?.[0]
              event.currentTarget.value = ''
              if (file) void insertImage(file)
            }}
          />
        </div>
        <div
          className={styles.toolGroup}
          onPointerDown={(event) => event.preventDefault()}
        >
          <button
            type="button"
            aria-label="Отменить"
            disabled={disabled}
            onClick={() => editor.dispatchCommand(UNDO_COMMAND, undefined)}
          >
            ↶
          </button>
          <button
            type="button"
            aria-label="Повторить действие"
            disabled={disabled}
            onClick={() => editor.dispatchCommand(REDO_COMMAND, undefined)}
          >
            ↷
          </button>
        </div>
      </div>
      <ErrorNotice error={error} />
    </>
  )
}
