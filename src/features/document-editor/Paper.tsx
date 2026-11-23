import { useLexicalComposerContext } from '@lexical/react/LexicalComposerContext'
import { ContentEditable } from '@lexical/react/LexicalContentEditable'
import { LexicalErrorBoundary } from '@lexical/react/LexicalErrorBoundary'
import { RichTextPlugin } from '@lexical/react/LexicalRichTextPlugin'
import { useEffect, useRef, useState, type CSSProperties } from 'react'
import type { TemplateParameters } from '../../shared/api/types'
import { templateVariables } from './template'
import styles from './DocumentEditor.module.css'

export function Paper({ parameters }: { parameters: TemplateParameters }) {
  const [editor] = useLexicalComposerContext()
  const viewport = useRef<HTMLDivElement>(null)
  const sheet = useRef<HTMLDivElement>(null)
  const [count, setCount] = useState(1)
  const [page, setPage] = useState(0)
  const [scaleChoice, setScaleChoice] = useState('fit')
  const [fitZoom, setFitZoom] = useState(85)
  const sheetWidth =
    ((parameters.orientation === 'portrait' ? 210 : 297) * 96) / 25.4
  const zoom = scaleChoice === 'fit' ? fitZoom : Number(scaleChoice)
  const stride = useRef(1)

  useEffect(() => {
    let frame = 0
    let alive = true
    let followCaret = false
    let observed: HTMLElement | null = null
    const observer = new ResizeObserver(schedule)

    function schedule() {
      if (!alive || frame) return
      frame = window.requestAnimationFrame(() => {
        frame = 0
        const root = editor.getRootElement()
        if (!root || !sheet.current || !viewport.current) return
        setFitZoom(
          Math.max(
            20,
            Math.min(
              85,
              Math.floor(
                ((viewport.current.clientWidth - 34) / sheetWidth) * 100,
              ),
            ),
          ),
        )
        const gap = parseFloat(getComputedStyle(root).columnGap) || 0
        const baseStride = root.clientWidth + gap
        if (baseStride <= 0) return
        const nextCount = Math.max(
          1,
          1 + Math.round((root.scrollWidth - root.clientWidth) / baseStride),
        )
        const scale =
          sheet.current.getBoundingClientRect().width /
          sheet.current.offsetWidth
        const previousStride = stride.current
        stride.current = baseStride * scale
        if (
          previousStride > 1 &&
          Math.abs(previousStride - stride.current) > 1
        ) {
          viewport.current.scrollLeft *= stride.current / previousStride
        }
        if (followCaret && root === root.ownerDocument.activeElement) {
          const selection = root.ownerDocument.getSelection()
          if (selection?.isCollapsed && root.contains(selection.anchorNode)) {
            const caret = selection.getRangeAt(0).getClientRects()[0]
            const view = viewport.current.getBoundingClientRect()
            if (caret && (caret.left < view.left || caret.right > view.right)) {
              const first = sheet.current.getBoundingClientRect()
              const index = Math.max(
                0,
                Math.min(
                  nextCount - 1,
                  Math.floor((caret.left - first.left) / stride.current),
                ),
              )
              viewport.current.scrollLeft = index * stride.current
            }
          }
        }
        followCaret = false
        setCount(nextCount)
        setPage(
          Math.min(
            nextCount - 1,
            Math.round(viewport.current.scrollLeft / stride.current),
          ),
        )
      })
    }

    const unregisterRoot = editor.registerRootListener((root) => {
      if (observed) observed.removeEventListener('load', schedule, true)
      observer.disconnect()
      observed = root
      if (root) {
        root.addEventListener('load', schedule, true)
        observer.observe(root)
      }
      if (viewport.current) observer.observe(viewport.current)
      schedule()
    })
    const unregisterUpdate = editor.registerUpdateListener(() => {
      followCaret = true
      schedule()
    })
    void document.fonts?.ready.then(schedule)
    return () => {
      alive = false
      window.cancelAnimationFrame(frame)
      unregisterRoot()
      unregisterUpdate()
      observer.disconnect()
      observed?.removeEventListener('load', schedule, true)
    }
  }, [editor, parameters, sheetWidth, zoom])

  function jump(index: number) {
    viewport.current?.scrollTo({ left: stride.current * index })
  }

  return (
    <div className={styles.paperWorkspace}>
      <div className={styles.navigation} aria-label="Просмотр листов">
        <div className={styles.pageControls}>
          <button
            type="button"
            aria-label="Предыдущий лист"
            disabled={page <= 0}
            onClick={() => jump(page - 1)}
          >
            ‹
          </button>
          <span data-testid="page-position">
            Лист {page + 1} из {count}
          </span>
          <button
            type="button"
            aria-label="Следующий лист"
            disabled={page >= count - 1}
            onClick={() => jump(page + 1)}
          >
            ›
          </button>
        </div>
        <label className={styles.zoom}>
          Масштаб
          <select
            value={scaleChoice}
            onChange={(event) => setScaleChoice(event.target.value)}
          >
            <option value="fit">По ширине</option>
            <option value={60}>60%</option>
            <option value={85}>85%</option>
            <option value={100}>100%</option>
            <option value={125}>125%</option>
          </select>
        </label>
      </div>
      <div
        ref={viewport}
        className={styles.viewport}
        style={
          {
            '--visible-sheet-width': `${(sheetWidth * zoom) / 100}px`,
          } as CSSProperties
        }
        onScroll={(event) =>
          setPage(
            Math.min(
              count - 1,
              Math.round(event.currentTarget.scrollLeft / stride.current),
            ),
          )
        }
      >
        <div
          className={styles.surface}
          style={
            {
              ...templateVariables(parameters),
              '--sheets': count,
              zoom: zoom / 100,
            } as CSSProperties
          }
        >
          <div className={styles.sheets} aria-hidden="true">
            {Array.from({ length: count }, (_, index) => (
              <div
                className={styles.sheet}
                key={index}
                ref={index === 0 ? sheet : undefined}
              >
                <span>{parameters.page_number_start + index}</span>
              </div>
            ))}
          </div>
          <RichTextPlugin
            contentEditable={
              <ContentEditable
                className={styles.editable}
                aria-label="Текст ВКР"
              />
            }
            ErrorBoundary={LexicalErrorBoundary}
          />
        </div>
      </div>
    </div>
  )
}
