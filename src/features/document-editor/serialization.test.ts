import { HeadingNode } from '@lexical/rich-text'
import {
  $createTextNode,
  $getRoot,
  $isParagraphNode,
  createEditor,
} from 'lexical'
import { expect, it } from 'vitest'
import {
  retainOriginalBlocks,
  serializeContent,
  type EditorContent,
} from './serialization'

it('keeps the wire representation of a reviewed chapter when another block changes', () => {
  const editor = createEditor({ namespace: 'test', nodes: [HeadingNode] })
  const raw = {
    root: {
      type: 'root',
      version: 1,
      format: '',
      direction: null,
      indent: 0,
      children: [
        {
          type: 'heading',
          version: 1,
          format: '',
          direction: null,
          indent: 0,
          tag: 'h1',
          $: { normaStageId: '5d96192f-199e-42e4-a0b4-49e4f9c06636' },
          children: [
            {
              type: 'text',
              version: 1,
              detail: 0,
              mode: 'normal',
              text: 'Глава',
              format: 0,
              style: '',
            },
          ],
        },
        {
          type: 'paragraph',
          version: 1,
          format: '',
          direction: null,
          indent: 0,
          children: [],
        },
      ],
    },
  }
  // Old API responses omit optional defaults which the generated output type marks as present.
  const original = raw as unknown as EditorContent
  editor.setEditorState(editor.parseEditorState(JSON.stringify(original)))
  const baseline = retainOriginalBlocks(editor.getEditorState(), original)
  editor.update(
    () => {
      const paragraph = $getRoot().getLastChild()
      if ($isParagraphNode(paragraph))
        paragraph.append($createTextNode('Новый текст').setStyle('color: red'))
    },
    { discrete: true },
  )
  const serialized = serializeContent(
    editor.getEditorState(),
    original,
    baseline,
  )
  expect(serialized.root.children[0]).toEqual(raw.root.children[0])
  expect(serialized.root.children[1].children).toEqual([
    expect.objectContaining({ text: 'Новый текст', style: '' }),
  ])
})
