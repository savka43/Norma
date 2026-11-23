import { describe, expect, it } from 'vitest'
import type { Version } from '../../shared/api/types'
import { textBlocks } from './snapshot'

const format = {
  version: 1,
  direction: null,
  indent: 0,
  format: '',
  textFormat: 0,
  textStyle: '',
} as const
const span = (text: string) =>
  ({
    type: 'text',
    version: 1,
    text,
    format: 0,
    detail: 0,
    mode: 'normal',
    style: '',
  }) as const

describe('review anchors', () => {
  it('keeps nested paths and the UTF-16 offsets sent to the comments API', () => {
    const content: Version['content'] = {
      root: {
        ...format,
        type: 'root',
        children: [
          {
            ...format,
            type: 'paragraph',
            children: [
              span('А😀'),
              { type: 'linebreak', version: 1 },
              {
                type: 'norma-image',
                version: 1,
                asset_id: '00000000-0000-4000-8000-000000000001',
                alt_text: 'Рисунок',
              },
              span('Текст'),
            ],
          },
          {
            ...format,
            type: 'table',
            children: [
              {
                ...format,
                type: 'tablerow',
                children: [
                  {
                    ...format,
                    type: 'tablecell',
                    headerState: 0,
                    colSpan: 1,
                    rowSpan: 1,
                    backgroundColor: null,
                    children: [
                      {
                        ...format,
                        type: 'paragraph',
                        children: [span('Ячейка')],
                      },
                    ],
                  },
                ],
              },
            ],
          },
        ],
      },
    }
    const blocks = textBlocks(content)
    expect(blocks.map(({ id, text }) => [id, text])).toEqual([
      ['0', 'А😀\n\ufffcТекст'],
      ['1/0/0/0', 'Ячейка'],
    ])
    expect(blocks[0].text.slice(1, 3)).toBe('😀')
  })
})
