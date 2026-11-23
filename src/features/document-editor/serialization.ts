import {
  $getRoot,
  type EditorState,
  type NodeKey,
  type SerializedLexicalNode,
} from 'lexical'
import type { Document } from '../../shared/api/types'

export type EditorContent = Document['content']
type WireNode = SerializedLexicalNode & Record<string, unknown>

function project(node: WireNode): WireNode {
  const base = { type: node.type, version: 1 }
  switch (node.type) {
    case 'text':
      return {
        ...base,
        text: node.text,
        detail: node.detail,
        format: Number(node.format) & 2047,
        mode: node.mode,
        style: '',
      }
    case 'linebreak':
      return base
    case 'norma-image':
      return { ...base, asset_id: node.asset_id, alt_text: node.alt_text }
  }

  const block = {
    ...base,
    children: (node.children as WireNode[]).map(project),
    direction: node.direction ?? null,
    format: node.format ?? '',
    indent: Number(node.indent ?? 0),
    textFormat: Number(node.textFormat ?? 0) & 2047,
    textStyle: '',
  }
  switch (node.type) {
    case 'heading': {
      const binding = (node.$ as { normaStageId?: string } | undefined)
        ?.normaStageId
      return binding && node.tag === 'h1'
        ? { ...block, tag: node.tag, $: { normaStageId: binding } }
        : { ...block, tag: node.tag }
    }
    case 'norma-caption':
      return { ...block, kind: node.kind }
    case 'list':
      return {
        ...block,
        listType: node.listType,
        tag: node.tag,
        start: node.start,
      }
    case 'listitem':
      return { ...block, value: node.value }
    case 'tablecell':
      return {
        ...block,
        headerState: node.headerState,
        colSpan: node.colSpan ?? 1,
        rowSpan: node.rowSpan ?? 1,
        backgroundColor: null,
      }
    default:
      return block
  }
}

type OriginalBlock = {
  comparable: string
  wire: EditorContent['root']['children'][number]
}

export function retainOriginalBlocks(state: EditorState, wire: EditorContent) {
  const keys = state.read(() => $getRoot().getChildrenKeys())
  const initial = project(state.toJSON().root as WireNode)
  const normalized = initial.children as WireNode[]
  return new Map<NodeKey, OriginalBlock>(
    wire.root.children.map((block, index) => [
      keys[index],
      { comparable: JSON.stringify(normalized[index]), wire: block },
    ]),
  )
}

export function serializeContent(
  state: EditorState,
  initial: EditorContent,
  originals: Map<NodeKey, OriginalBlock>,
): EditorContent {
  const root = project(state.toJSON().root as WireNode)
  const keys = state.read(() => $getRoot().getChildrenKeys())
  const children = (root.children as WireNode[]).map((block, index) => {
    const original = originals.get(keys[index])
    return original?.comparable === JSON.stringify(block)
      ? original.wire
      : block
  })
  // Root presentation comes from the pinned template. Carry its saved fields
  // through so editing outside a reviewed chapter leaves them identical.
  return {
    root: {
      ...initial.root,
      children: children as EditorContent['root']['children'],
    },
  }
}
