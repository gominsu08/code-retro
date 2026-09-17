import type { SourceFile } from './types';

export type FolderNode = {
  name: string;
  path: string;
  fileIds: string[];
  selectableIds: string[];
  children: FolderNode[];
};

export function canSelectFile(file: Pick<SourceFile, 'category'>) {
  return !['unsupported', 'oversize'].includes(file.category);
}

export function isInFolder(path: string, folder: string) {
  return !folder || path.startsWith(folder + '/');
}

export function selectionState(ids: readonly string[], selected: ReadonlySet<string>) {
  const count = ids.filter(id => selected.has(id)).length;
  return { count, checked: ids.length > 0 && count === ids.length, mixed: count > 0 && count < ids.length };
}

export function buildFolderTree(files: readonly Pick<SourceFile, 'id' | 'path' | 'category'>[]): FolderNode[] {
  const roots: FolderNode[] = [];
  const byPath = new Map<string, FolderNode>();
  for (const file of files) {
    let siblings = roots;
    let path = '';
    for (const name of file.path.split('/').slice(0, -1)) {
      path = path ? `${path}/${name}` : name;
      let node = byPath.get(path);
      if (!node) {
        node = { name, path, fileIds: [], selectableIds: [], children: [] };
        byPath.set(path, node);
        siblings.push(node);
      }
      node.fileIds.push(file.id);
      if (canSelectFile(file)) node.selectableIds.push(file.id);
      siblings = node.children;
    }
  }
  const sort = (nodes: FolderNode[]) => {
    nodes.sort((a, b) => a.name.localeCompare(b.name, 'ko', { numeric: true }));
    nodes.forEach(node => sort(node.children));
  };
  sort(roots);
  return roots;
}
