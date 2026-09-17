import { useEffect, useRef, useState } from 'react';
import { ArrowRight, BookOpen, Braces, Check, ChevronDown, CircleHelp, Download, FolderGit2, GitBranch, GitFork as Github, LoaderCircle, Plus, RefreshCw, Settings2, ShieldCheck, X } from 'lucide-react';
import { api, setCsrf } from './api';
import { activeStatuses, type Job, type Project, type Session, type SourceFile, type System } from './types';
import ScopePage from './ScopePage';
import Workspace from './Workspace';
import ExportPage from './ExportPage';

type Page = 'connect' | 'scope' | 'workspace' | 'export';
export type RunAction = (action: () => Promise<void>) => Promise<void>;

export default function App() {
  const [session, setSession] = useState<Session | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [project, setProject] = useState<Project | null>(null);
  const [files, setFiles] = useState<SourceFile[]>([]);
  const [systems, setSystems] = useState<System[]>([]);
  const [page, setPage] = useState<Page>('connect');
  const [job, setJob] = useState<Job | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const [projectMenu, setProjectMenu] = useState(false);
  const initialized = useRef(false);
  const currentId = useRef<string | null>(null);
  const requestSequence = useRef(0);
  currentId.current = project?.id || null;

  const run: RunAction = async (action) => {
    setBusy(true); setError('');
    try { await action(); } catch (e) { setError(e instanceof Error ? e.message : '문제가 발생했습니다. 다시 시도해주세요.'); }
    finally { setBusy(false); }
  };
  async function refresh(id = currentId.current) {
    if (!id) return;
    const sequence = ++requestSequence.current;
    const [p, f, s] = await Promise.all([api<Project>(`/projects/${id}`), api<{ files: SourceFile[] }>(`/projects/${id}/files`), api<{ systems: System[] }>(`/projects/${id}/systems`)]);
    if (sequence !== requestSequence.current) return;
    setProject(p); setFiles(f.files); setSystems(s.systems);
    setProjects(list => { const old = list.filter(x => x.id !== id); return [p, ...old]; });
    localStorage.setItem('code-retro-project', id);
    return p;
  }
  async function selectProject(p: Project) {
    setProjectMenu(false);
    const fresh = await refresh(p.id);
    if (!fresh) return;
    setPage(fresh.current_run_id ? 'workspace' : fresh.snapshot ? 'scope' : 'connect');
    setJob(fresh.jobs.find(j => activeStatuses.includes(j.status)) || fresh.jobs[0] || null);
  }
  useEffect(() => {
    if (initialized.current) return;
    initialized.current = true;
    void run(async () => {
      const s = await api<Session>('/session', 'POST'); setCsrf(s.csrf_token); setSession(s);
      const list = await api<{ projects: Project[] }>('/projects'); setProjects(list.projects);
      const recent = list.projects.find(p => p.id === localStorage.getItem('code-retro-project')) || list.projects[0];
      if (recent) await selectProject(recent);
    });
  }, []);
  useEffect(() => {
    if (!job || !activeStatuses.includes(job.status)) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const latest = await api<Job>(`/jobs/${job.id}`);
        if (stopped) return;
        setJob(latest);
        if (!activeStatuses.includes(latest.status)) {
          const p = await refresh(latest.project_id);
          if (p && latest.kind === 'prepare' && p.snapshot) setPage('scope');
          if (p && latest.kind === 'analyze' && p.current_run_id) setPage('workspace');
          if (latest.status === 'succeeded') setNotice(latest.kind === 'prepare' ? '저장소를 연결했습니다. 분석할 파일을 확인해주세요.' : '작업 결과를 저장했습니다.');
          return;
        }
      } catch (e) { if (!stopped) setError(e instanceof Error ? e.message : '작업 상태를 확인하지 못했습니다.'); }
      if (!stopped) timer = setTimeout(poll, 1800);
    };
    timer = setTimeout(poll, 600);
    return () => { stopped = true; clearTimeout(timer); };
  }, [job?.id, job?.status]);
  useEffect(() => { if (notice) { const t = setTimeout(() => setNotice(''), 4500); return () => clearTimeout(t); } }, [notice]);
  const active = !!job && activeStatuses.includes(job.status);
  const base = project ? `/projects/${project.id}` : '';
  async function created(id: string, nextJob: Job) { await refresh(id); setJob(nextJob); }

  return <div className="app-shell">
    <header className="topbar">
      <button className="brand" onClick={() => { if (project) setPage(project.current_run_id ? 'workspace' : 'scope'); else setPage('connect'); }}><span className="brand-mark"><Braces size={20} /></span><span>code<span className="brand-light">retro</span><small>BETA</small></span></button>
      <span className="top-divider" />
      <div className="project-selector">
        <button className="project-trigger" aria-expanded={projectMenu} onClick={() => setProjectMenu(!projectMenu)}><FolderGit2 size={16} /><span>{project?.name || '새 프로젝트'}</span><ChevronDown size={14} /></button>
        {projectMenu && <div className="project-menu">{projects.map(p => <button key={p.id} disabled={busy || active} onClick={() => void run(() => selectProject(p))}><FolderGit2 size={15} /><span>{p.name}</span>{p.id === project?.id && <Check size={14} />}</button>)}<button disabled={active} onClick={() => { setPage('connect'); setProjectMenu(false); }}><Plus size={15} />새 프로젝트 연결</button><p>이 브라우저의 세션에 저장됩니다.<br />쿠키를 지우면 작업 공간에 접근할 수 없습니다.</p></div>}
      </div>
      <div className="top-spacer" /><span className={`connection-status ${session?.capabilities.ai_enabled ? 'ready' : ''}`}><i />{session?.capabilities.ai_enabled ? 'AI 연결됨' : '코드 분석 모드'}</span>
      {project && <button className="icon-button" title="프로젝트 설정" aria-label="프로젝트 설정" onClick={() => setSettingsOpen(true)}><Settings2 size={18} /></button>}
      <button className="icon-button help-link" title="사용 방법" aria-label="사용 방법" onClick={() => setHelpOpen(true)}><CircleHelp size={18} /></button>
    </header>
    <nav className="steps" aria-label="작업 단계">{([
      ['connect', '저장소 연결', Github], ['scope', '분석 범위', FolderGit2], ['workspace', '시스템 회고', BookOpen], ['export', '내보내기', Download],
    ] as const).map(([id, label, Icon], index) => <button key={id} className={page === id ? 'active' : ''} disabled={(id === 'scope' && !project?.snapshot) || ((id === 'workspace' || id === 'export') && !systems.length) || (id === 'connect' && active)} onClick={() => setPage(id)}><span className="step-number">{index + 1}</span><Icon size={15} /><span>{label}</span></button>)}<span className="step-trailing">코드를 다시 읽고, 내 경험으로 남기기</span></nav>
    {error && <div role="alert" className="message error"><span>{error}</span><button className="icon-button" aria-label="오류 닫기" onClick={() => setError('')}><X size={16} /></button></div>}
    {notice && <div role="status" className="toast"><Check size={16} />{notice}</div>}
    {job && (active || job.status === 'failed' || job.status === 'partial' || job.status === 'cancelled') && <div className={`jobbar ${job.status === 'failed' ? 'failed' : ''}`} aria-live="polite">
      {active ? <LoaderCircle size={16} className="spin" /> : <CircleHelp size={16} />}<div className="job-title"><strong>{job.stage}</strong><span>{job.error?.message || (job.status === 'cancelled' ? '저장된 코드와 설명은 그대로 유지됩니다.' : job.status === 'partial' ? '일부 파일 또는 AI 설명이 완료되지 않았습니다. 수집된 내용부터 확인할 수 있습니다.' : job.status === 'waiting_retry' ? '요청 한도 또는 연결 상태를 확인하며 대기합니다.' : '페이지를 이동해도 서버에서 작업을 계속합니다.')}</span></div>
      {active && <><progress value={job.progress.completed || 0} max={job.progress.total || 1} /><span className="mono">{job.progress.completed || 0}/{job.progress.total || '…'}</span><button className="button subtle small" onClick={() => void run(async () => setJob(await api<Job>(`/jobs/${job.id}/cancel`, 'POST')))} disabled={busy || job.status === 'cancel_requested'}>취소</button></>}
      {!active && <button className="button small" disabled={busy} onClick={() => void run(async () => { const result = await api<{ job: Job }>(`/jobs/${job.id}/retry`, 'POST'); setJob(result.job); })}><RefreshCw size={13} />다시 시도</button>}
      {!active && <button className="icon-button" aria-label="작업 안내 닫기" onClick={() => setJob(null)}><X size={15} /></button>}
    </div>}
    {!session && !error && <div className="empty-state"><LoaderCircle className="spin" /><p>작업 공간을 준비하고 있습니다.</p></div>}
    {session && page === 'connect' && <ConnectPage busy={busy || active} run={run} created={created} projects={projects} open={p => void run(() => selectProject(p))} />}
    {session && page === 'scope' && project && <ScopePage key={project.id} project={project} files={files} busy={busy || active} aiEnabled={session.capabilities.ai_enabled} run={run} refresh={refresh} setJob={setJob} />}
    {session && page === 'workspace' && project && <Workspace project={project} files={files} systems={systems} busy={busy || active} aiEnabled={session.capabilities.ai_enabled} run={run} refresh={refresh} setJob={setJob} notify={setNotice} />}
    {session && page === 'export' && project && <ExportPage project={project} systems={systems} busy={busy || active} run={run} notify={setNotice} />}
    <footer className="statusbar"><span><ShieldCheck size={13} />공개 저장소 · 세션별 작업 공간</span><span>{project?.snapshot && <><GitBranch size={12} />{project.snapshot.ref}<code>{project.snapshot.commit_sha.slice(0, 7)}</code><span className="status-separator">/</span>설정 v{project.config_version}</>}</span><span>{files.length ? `${files.length} C# files` : 'Unity · C#'}<span className="status-separator">/</span>Code Retro 0.1</span></footer>
    {settingsOpen && project && <ProjectSettings project={project} busy={busy || active} run={run} close={() => setSettingsOpen(false)} saved={async () => { await refresh(); setSettingsOpen(false); setNotice('프로젝트 설정을 저장했습니다. 새 설정으로 다시 분석해주세요.'); }} base={base} />}
    {helpOpen && <HelpDialog close={() => setHelpOpen(false)} />}
  </div>;
}

function HelpDialog({ close }: { close: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => { dialog.current?.showModal(); }, []);
  return <dialog ref={dialog} className="modal help-modal" onCancel={close} aria-labelledby="help-title"><div className="section-heading"><h2 id="help-title">코드를 회고하는 순서</h2><button className="icon-button" aria-label="도움말 닫기" onClick={close}><X size={18} /></button></div><ol className="help-steps"><li><strong>저장소 연결</strong><p>공개 GitHub 저장소 주소와 내 아이디를 입력하고 개인·팀 프로젝트를 선택하세요.</p></li><li><strong>분석 범위 확인</strong><p>프로젝트 코드와 담당 범위를 확인한 뒤 분석을 시작하세요. 담당 후보는 직접 보정할 수 있습니다.</p></li><li><strong>AI 설명과 코멘트</strong><p>시스템을 선택해 AI 설명을 생성하세요. 문단의 코드 근거를 읽고, 코멘트를 저장한 뒤 선택한 코멘트로 새 버전을 만드세요. 이전 버전도 보존됩니다.</p></li><li><strong>검토하고 내보내기</strong><p>실제 담당 내용과 개발 의도를 확인한 설명에 검토 완료를 표시하세요. 내보내기에서 상세 내용과 코드 링크를 Markdown으로 받을 수 있습니다.</p></li></ol><p className="micro-copy">먼저 필요한 시스템 하나부터 AI로 설명하면 무료 요청 한도를 아낄 수 있습니다. 작업은 이 브라우저의 쿠키로 연결되며, 30일 동안 사용하지 않은 작업 공간은 정리됩니다. 쿠키를 지우기 전에 문서를 내보내세요.</p><div className="modal-actions"><button className="button primary" onClick={close}>확인</button></div></dialog>;
}

function ConnectPage({ busy, run, created, projects, open }: { busy: boolean; run: RunAction; created: (id: string, job: Job) => Promise<void>; projects: Project[]; open: (p: Project) => void }) {
  const [url, setUrl] = useState(''); const [username, setUsername] = useState(''); const [type, setType] = useState<'team' | 'solo'>('team'); const [ref, setRef] = useState('');
  return <main className="connect-page"><div className="connect-intro"><span className="eyebrow"><span />YOUR CODE, YOUR STORY</span><h1>어떤 코드를<br /><span>다시 떠올려볼까요?</span></h1><p>흩어진 코드에서 개발의 맥락을 찾고,<br />코멘트를 더해 나만의 포트폴리오 문장으로 정리하세요.</p><div className="intro-flow"><div><FolderGit2 size={18} /><span>시스템별로 살펴보고</span></div><div><Braces size={18} /><span>실제 코드로 확인하고</span></div><div><BookOpen size={18} /><span>내 경험을 더해 정리하기</span></div></div><div className="intro-note"><GitBranch size={16} /><div><strong>한 커밋을 기준으로 정확하게</strong><span>설명과 코드 근거가 같은 버전을 가리킵니다.</span></div></div></div>
    <div className="connect-right"><form className="connect-card" onSubmit={e => { e.preventDefault(); void run(async () => { const data = await api<{ project_id: string; job: Job }>('/projects', 'POST', { repo_url: url, github_username: username, project_type: type, ref }); await created(data.project_id, data.job); }); }}><div className="card-title"><span className="square-icon"><Github size={22} /></span><div><h2>GitHub 저장소 연결</h2><p>공개 Unity · C# 프로젝트부터 시작합니다.</p></div></div><label>저장소 URL<input type="url" placeholder="https://github.com/username/project" value={url} onChange={e => setUrl(e.target.value)} required disabled={busy} /></label><button type="button" className="text-button sample" disabled={busy} onClick={() => { setUrl('https://github.com/gominsu08/2025_Engine_TeamProject'); setUsername('gominsu08'); }}>지정한 예시 저장소 입력 <ArrowRight size={12} /></button><div className="form-row"><label>내 GitHub 아이디<input autoComplete="username" placeholder="username" value={username} onChange={e => setUsername(e.target.value)} required maxLength={40} disabled={busy} /></label><label>브랜치 또는 태그 <span className="optional">선택</span><input placeholder="기본 브랜치" value={ref} onChange={e => setRef(e.target.value)} disabled={busy} /></label></div><fieldset><legend>어떤 프로젝트인가요?</legend><div className="type-options">{(['team', 'solo'] as const).map(value => <label key={value} className={value === type ? 'selected' : ''}><input type="radio" name="project-type" value={value} checked={type === value} disabled={busy} onChange={() => setType(value)} /><div><strong>{value === 'team' ? '팀 프로젝트' : '개인 프로젝트'}</strong><span>{value === 'team' ? '담당 범위를 함께 구분해요' : '전체 구조를 중심으로 살펴봐요'}</span></div></label>)}</div></fieldset><div className="hint"><ShieldCheck size={16} /><span>네임스페이스·스타일은 담당 구분의 힌트로 사용하며,<br />실제 담당 범위는 직접 확인하고 수정할 수 있습니다.</span></div><button className="button primary full" disabled={busy || !url || !username}>{busy ? <LoaderCircle size={16} className="spin" /> : <Github size={16} />}저장소 연결하기<ArrowRight size={16} /></button><p className="form-footnote">프로젝트를 실행하지 않고 선택한 소스 코드만 읽습니다.<br />AI 생성 시 선택한 코드와 코멘트가 Google Gemini로 전송되며,<br />무료 API의 제품 개선에 사용될 수 있습니다. 민감한 정보는 입력하지 마세요.</p></form>{projects.length > 0 && <div className="recent-projects"><span className="eyebrow">이어서 작업하기</span>{projects.slice(0, 3).map(p => <button key={p.id} disabled={busy} onClick={() => open(p)}><FolderGit2 size={16} /><span>{p.name}<small>{p.github_username} · {p.project_type === 'team' ? '팀 프로젝트' : '개인 프로젝트'}</small></span><ArrowRight size={15} /></button>)}</div>}</div>
  </main>;
}

function ProjectSettings({ project, busy, run, close, saved, base }: { project: Project; busy: boolean; run: RunAction; close: () => void; saved: () => Promise<void>; base: string }) {
  const [name, setName] = useState(project.name); const [username, setUsername] = useState(project.github_username); const [type, setType] = useState(project.project_type);
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => { dialog.current?.showModal(); }, []);
  return <dialog ref={dialog} className="modal" onCancel={close}><form onSubmit={e => { e.preventDefault(); void run(async () => { await api(base, 'PATCH', { expected_version: project.config_version, name, github_username: username, project_type: type }); await saved(); }); }}><div className="section-heading"><h2>프로젝트 설정</h2><button type="button" className="icon-button" aria-label="닫기" onClick={close}><X size={18} /></button></div><p className="muted">기준 계정과 프로젝트 유형을 바꾸면 기존 설명은 이전 설정의 결과로 보존됩니다.</p><label>프로젝트 이름<input value={name} onChange={e => setName(e.target.value)} required maxLength={200} /></label><label>내 GitHub 아이디<input value={username} onChange={e => setUsername(e.target.value)} required maxLength={40} /></label><label>프로젝트 유형<select value={type} onChange={e => setType(e.target.value as 'team' | 'solo')}><option value="team">팀 프로젝트</option><option value="solo">개인 프로젝트</option></select></label><div className="modal-actions"><button type="button" className="button" onClick={close}>취소</button><button className="button primary" disabled={busy}>설정 저장</button></div></form></dialog>;
}
