// Tooling-only packages, pinned to 0.53.0. Also verifies imported JSON if supplied.
const {createRequire} = require('node:module');
const {resolve, join} = require('node:path');
const {writeFileSync, readFileSync} = require('node:fs');
const {deepStrictEqual, equal} = require('node:assert');
const load = createRequire(join(resolve(process.argv[2]), 'package.json'));
const {DecoratorNode, $getRoot, $createParagraphNode, $createTextNode} = load('lexical');
const {createHeadlessEditor} = load('@lexical/headless');
const {HeadingNode, QuoteNode} = load('@lexical/rich-text');
const {ListNode, ListItemNode} = load('@lexical/list');
const {TableNode, TableRowNode, TableCellNode, $createTableNodeWithDimensions} = load('@lexical/table');
// Serialization probe for the custom node; this is not the frontend renderer.
class NormaImageNode extends DecoratorNode {
  static getType() { return 'norma-image'; }
  static clone(node) { return new NormaImageNode(node.asset_id, node.alt_text, node.__key); }
  constructor(asset_id, alt_text, key) { super(key); this.asset_id = asset_id; this.alt_text = alt_text; }
  static importJSON(data) { return new NormaImageNode(data.asset_id, data.alt_text); }
  exportJSON() { return {...super.exportJSON(), type: 'norma-image', version: 1,
    asset_id: this.asset_id, alt_text: this.alt_text}; }
  isInline() { return true; }
  createDOM() { throw new Error('headless serialization only'); }
  updateDOM() { return false; }
  decorate() { return null; }
}
const config = {namespace: 'norma-table-fixture',
  nodes: [HeadingNode, QuoteNode, ListNode, ListItemNode, TableNode, TableRowNode, TableCellNode, NormaImageNode],
  onError(error) { throw error; }};
const editor = createHeadlessEditor(config);
editor.update(() => {
  const table = $createTableNodeWithDimensions(2, 2, false);
  table.getFirstChild().getFirstChild().getFirstChild().append($createTextNode('Ячейка'));
  $getRoot().append(table, $createParagraphNode().append(
    new NormaImageNode('00000000-0000-0000-0000-000000000001', 'Тестовый рисунок')));
}, {discrete: true});
const serialized = JSON.parse(JSON.stringify(editor.getEditorState().toJSON()));
const reader = createHeadlessEditor(config);
reader.setEditorState(reader.parseEditorState(JSON.stringify(serialized)));
deepStrictEqual(JSON.parse(JSON.stringify(reader.getEditorState().toJSON())), serialized);
writeFileSync(process.argv[3], JSON.stringify(serialized, null, 2) + '\n');
if (process.argv[4]) {
  const imported = JSON.parse(readFileSync(process.argv[4], 'utf8'));
  const probe = createHeadlessEditor(config);
  probe.setEditorState(probe.parseEditorState(JSON.stringify(imported)));
  const nodes = state => { const result = []; const walk = n => {
    if (n.type === 'text') result.push(['text', n.text, n.format]);
    if (n.type === 'norma-image') result.push(['image', n.asset_id, n.alt_text]);
    if (n.type === 'table') result.push(['table', n.children.length]);
    if (n.children) n.children.forEach(walk);
  }; walk(state.root); return result; };
  deepStrictEqual(nodes(probe.getEditorState().toJSON()), nodes(imported));
  equal(probe.getEditorState().isEmpty(), false);
}
