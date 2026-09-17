import { useEffect, useMemo, useRef, useState } from 'react';
import { ChevronRight, Folder, FolderOpen, ShieldCheck } from 'lucide-react';
import type { SourceFile } from './types';
import { buildFolderTree, selectionState, type FolderNode } from './folderTree';

export function SelectionCheckbox({ ids, selected, disabled, label, onChange }: {
  ids: string[]; selected: ReadonlySet<string>; disabled: boolean; label: string; onChange: (checked: boolean) => void;
}) {
  const input = useRef<HTMLInputElement>(null);
  const state = selectionState(ids, selected);
  useEffect(() => { if (input.current) input.current.indeterminate = state.mixed; }, [state.mixed]);
  return <input ref={input} type="checkbox" aria-label={label} aria-checked={state.mixed ? 'mixed' : state.checked} checked={state.checked} disabled={disabled || !ids.length} onChange={e => onChange(e.target.checked)} />;
}

export default function ScopeFolders({ files, selected, folder, busy, onFolderChange, onSelectionChange }: {
  files: SourceFile[]; selected: ReadonlySet<string>; folder: string; busy: boolean;
  onFolderChange: (path: string) => void; onSelectionChange: (ids: string[], selected: boolean) => void;
}) {
  const tree = useMemo(() => buildFolderTree(files), [files]);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  function entry(node: FolderNode, depth: number) {
    const open = expanded[node.path] ?? depth < 2;
    const count = selectionState(node.fileIds, selected).count;
    return <li key={node.path}>
      <div className={`folder-row ${folder === node.path ? 'active' : ''}`} style={{ paddingLeft: 7 + Math.min(depth, 4) * 10 }}>
        {node.children.length > 0 ? <button className={`folder-toggle ${open ? 'expanded' : ''}`} aria-label={`${node.path} 폴더 ${open ? '접기' : '펼치기'}`} aria-expanded={open} onClick={() => setExpanded(old => ({ ...old, [node.path]: !open }))}><ChevronRight size={13} /></button> : <span className="folder-toggle-space" />}
        <label className="folder-check" title="이 폴더의 하위 파일까지 함께 선택합니다."><SelectionCheckbox ids={node.selectableIds} selected={selected} disabled={busy} label={`${node.path} 폴더 전체 선택`} onChange={checked => onSelectionChange(node.selectableIds, checked)} /></label>
        <button className="folder-entry" title={node.path} aria-label={`${node.path} 폴더 보기`} aria-current={folder === node.path ? 'location' : undefined} onClick={() => { onFolderChange(node.path); setExpanded(old => ({ ...old, [node.path]: true })); }}>
          {open && node.children.length ? <FolderOpen size={14} /> : <Folder size={14} />}<span>{node.name}</span><small title={`${node.fileIds.length}개 중 ${count}개 선택`}>{count}/{node.fileIds.length}</small>
        </button>
      </div>
      {!!node.children.length && open && <ul>{node.children.map(child => entry(child, depth + 1))}</ul>}
    </li>;
  }
  return <aside className="scope-folders" aria-label="폴더 탐색기">
    <div className="panel-label">폴더 탐색 <span>{files.length}</span></div>
    <button className={`folder-entry folder-root ${!folder ? 'active' : ''}`} aria-current={!folder ? 'location' : undefined} onClick={() => onFolderChange('')}><Folder size={15} /><span>전체 C# 파일</span></button>
    <p className="folder-help">폴더를 체크하면 하위 파일도 함께 선택돼요.</p>
    <div className="folder-list"><ul>{tree.map(node => entry(node, 0))}</ul>{!tree.length && <p className="folder-help">하위 폴더 없이 저장소에 바로 있는 파일입니다.</p>}</div>
    <div className="folder-note"><ShieldCheck size={17} /><p>선택한 C# 파일만 읽습니다.<br />프로젝트는 실행하지 않습니다.</p></div>
  </aside>;
}
