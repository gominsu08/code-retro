import assert from 'node:assert/strict';
import test from 'node:test';
import { buildFolderTree, isInFolder, selectionState } from '../src/folderTree.ts';

const files = [
  { id: 'root', path: 'Root.cs', category: 'project' },
  { id: 'ui', path: 'Assets/Game/UI/Panel.cs', category: 'project' },
  { id: 'deep', path: 'Assets/Game/UI/Widgets/Button.cs', category: 'project' },
  { id: 'other', path: 'Assets/Game/UIExtra/Panel.cs', category: 'project' },
  { id: 'large', path: 'Assets/Game/UI/Generated.cs', category: 'oversize' },
];

test('중간 폴더를 포함한 트리를 만들고 하위 파일을 부모에 집계한다', () => {
  const [assets] = buildFolderTree(files);
  assert.equal(assets.path, 'Assets');
  const [game] = assets.children;
  assert.equal(game.path, 'Assets/Game');
  const ui = game.children.find(node => node.name === 'UI')!;
  assert.deepEqual(ui.fileIds, ['ui', 'deep', 'large']);
  assert.deepEqual(ui.selectableIds, ['ui', 'deep']);
  assert.equal(ui.children[0].path, 'Assets/Game/UI/Widgets');
  assert.ok(!assets.fileIds.includes('root'));
});

test('폴더 필터는 이름이 비슷한 형제 폴더를 포함하지 않는다', () => {
  assert.deepEqual(files.filter(f => isInFolder(f.path, 'Assets/Game/UI')).map(f => f.id), ['ui', 'deep', 'large']);
  assert.equal(files.filter(f => isInFolder(f.path, '')).length, files.length);
});

test('일부 선택과 전체 선택을 구분하고 선택 불가 폴더를 전체 선택으로 표시하지 않는다', () => {
  assert.deepEqual(selectionState(['ui', 'deep'], new Set(['ui'])), { count: 1, checked: false, mixed: true });
  assert.deepEqual(selectionState(['ui', 'deep'], new Set(['ui', 'deep'])), { count: 2, checked: true, mixed: false });
  assert.deepEqual(selectionState([], new Set()), { count: 0, checked: false, mixed: false });
});
