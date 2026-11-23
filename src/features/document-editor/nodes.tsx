import {
  $createParagraphNode,
  DecoratorNode,
  ElementNode,
  type NodeKey,
  type RangeSelection,
  type SerializedElementNode,
  type SerializedLexicalNode,
} from 'lexical'
import { createContext, useContext } from 'react'
import styles from './DocumentEditor.module.css'

export const ImageDocument = createContext('')

function DocumentImage({ assetId, alt }: { assetId: string; alt: string }) {
  const documentId = useContext(ImageDocument)
  return (
    <img
      className={styles.image}
      src={`/api/v1/documents/${documentId}/assets/${assetId}`}
      alt={alt}
      draggable={false}
    />
  )
}

type SerializedImage = SerializedLexicalNode & {
  asset_id: string
  alt_text: string
}

export class ImageNode extends DecoratorNode<React.JSX.Element> {
  __assetId: string
  __alt: string

  constructor(assetId: string, alt: string, key?: NodeKey) {
    super(key)
    this.__assetId = assetId
    this.__alt = alt
  }

  static getType() {
    return 'norma-image'
  }

  static clone(node: ImageNode) {
    return new ImageNode(node.__assetId, node.__alt, node.__key)
  }

  static importJSON(data: SerializedImage) {
    return new ImageNode(data.asset_id, data.alt_text)
  }

  exportJSON(): SerializedImage {
    return {
      ...super.exportJSON(),
      asset_id: this.__assetId,
      alt_text: this.__alt,
    }
  }

  createDOM() {
    return document.createElement('span')
  }

  updateDOM() {
    return false
  }

  isInline() {
    return true
  }

  decorate() {
    return <DocumentImage assetId={this.__assetId} alt={this.__alt} />
  }
}

type CaptionKind = 'figure' | 'table'
type SerializedCaption = SerializedElementNode & { kind: CaptionKind }

export class CaptionNode extends ElementNode {
  __kind: CaptionKind

  constructor(kind: CaptionKind, key?: NodeKey) {
    super(key)
    this.__kind = kind
  }

  static getType() {
    return 'norma-caption'
  }

  static clone(node: CaptionNode) {
    return new CaptionNode(node.__kind, node.__key)
  }

  static importJSON(data: SerializedCaption) {
    return new CaptionNode(data.kind).updateFromJSON(data)
  }

  exportJSON(): SerializedCaption {
    return { ...super.exportJSON(), kind: this.__kind }
  }

  createDOM() {
    const paragraph = document.createElement('p')
    paragraph.dataset.caption = this.__kind
    return paragraph
  }

  updateDOM(previous: CaptionNode, dom: HTMLElement) {
    if (previous.__kind !== this.__kind) dom.dataset.caption = this.__kind
    return false
  }

  insertNewAfter(_selection: RangeSelection, restoreSelection?: boolean) {
    const paragraph = $createParagraphNode()
    this.insertAfter(paragraph, restoreSelection)
    return paragraph
  }
}
