// Run with a tooling-only npm prefix containing Lexical 0.53.0; see docs/development.md.
const {createRequire} = require('node:module');
const {resolve, join} = require('node:path');
const {writeFileSync} = require('node:fs');
const {deepStrictEqual} = require('node:assert');
const load = createRequire(join(resolve(process.argv[2]), 'package.json'));
const {$getRoot, $createParagraphNode, $createTextNode, $createLineBreakNode} = load('lexical');
const {createHeadlessEditor} = load('@lexical/headless');
const {HeadingNode, QuoteNode, $createHeadingNode, $createQuoteNode} = load('@lexical/rich-text');
const {ListNode, ListItemNode, $createListNode, $createListItemNode} = load('@lexical/list');
const config = {namespace: 'norma-schema-fixture', nodes: [HeadingNode, QuoteNode, ListNode, ListItemNode],
  onError(error) { throw error; }};
const editor = createHeadlessEditor(config);
editor.update(() => {
  const nested = $createListNode('number').append($createListItemNode().append($createTextNode('Вложенный пункт')));
  $getRoot().append(
    $createHeadingNode('h1').append($createTextNode('Тестовая ВКР')),
    $createParagraphNode().append($createTextNode('Полужирный ').toggleFormat('bold'),
      $createTextNode('и курсив').toggleFormat('italic'), $createLineBreakNode(), $createTextNode('Новая строка')),
    $createQuoteNode().append($createTextNode('Цитата')),
    $createListNode('bullet').append($createListItemNode().append($createTextNode('Пункт')),
      $createListItemNode().append(nested)),
  );
}, {discrete: true});
const serialized = JSON.parse(JSON.stringify(editor.getEditorState().toJSON()));
const reader = createHeadlessEditor(config);
reader.setEditorState(reader.parseEditorState(JSON.stringify(serialized)));
deepStrictEqual(JSON.parse(JSON.stringify(reader.getEditorState().toJSON())), serialized);
writeFileSync(process.argv[3], JSON.stringify(serialized, null, 2) + '\n');
