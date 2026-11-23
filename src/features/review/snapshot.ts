import type { Version } from '../../shared/api/types'

type Node = {
  type: string
  children?: Node[]
  text?: string
  kind?: string
  value?: number
  tag?: string
}

export type TextBlock = { id: string; text: string; type: string }

function inlineText(node: Node): string {
  if (node.type === 'text') return node.text ?? ''
  if (node.type === 'linebreak') return '\n'
  if (node.type === 'norma-image') return '\ufffc'
  return (node.children ?? [])
    .filter((child) => child.type !== 'list')
    .map(inlineText)
    .join('')
}

/** Matches the snapshot paths and UTF-16 offsets accepted by the comments API. */
export function textBlocks(content: Version['content']): TextBlock[] {
  const blocks: TextBlock[] = []
  function visit(node: Node, id: string) {
    if (
      ['paragraph', 'heading', 'quote', 'norma-caption', 'listitem'].includes(
        node.type,
      )
    ) {
      const text = inlineText(node)
      if (text.trim()) blocks.push({ id, text, type: node.type })
    }
    node.children?.forEach((child, index) =>
      visit(child, id ? `${id}/${index}` : String(index)),
    )
  }
  visit(content.root, '')
  return blocks
}
