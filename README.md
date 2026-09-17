# Code Retro · 코드 회고

공개 GitHub의 Unity/C# 프로젝트를 다시 읽고, 시스템별 설명에 개발 경험을 더해 포트폴리오 초안을 만드는 웹 도구입니다.

**[공개 웹 서비스](https://code-retro-rxox.onrender.com/)에서 바로 사용할 수 있습니다.** 저장소 연결·코드 분석·실제 Gemini 설명 생성·코멘트 반영·검토·Markdown 다운로드를 검증했습니다. 무료 서버는 한동안 접속이 없으면 쉬었다가 다시 시작하므로 첫 화면이 늦게 열릴 수 있습니다.

## 이 PC에서 실행

전용 환경과 웹 빌드, Gemini 설정이 준비되어 있습니다. PowerShell에서 실행합니다.

```powershell
Set-Location D:\Server_AI_Agent
.\.venv\Scripts\python.exe -m server.launch
```

[로컬 웹 화면](http://127.0.0.1:8000/)을 열고, 터미널에서 `Ctrl+C`로 종료합니다. 실행 중인 서버가 있으면 중복 실행하지 않습니다. `localhost`와 `127.0.0.1`은 쿠키가 다르므로 위 주소를 일관되게 사용합니다. 이 주소는 해당 PC에서만 접속할 수 있습니다.

웹 코드를 수정했다면 먼저 빌드합니다.

```powershell
Set-Location D:\Server_AI_Agent\web
npm.cmd run build
Set-Location ..
.\.venv\Scripts\python.exe -m server.launch
```

이미 PowerShell 스크립트 실행이 허용된 환경에서는 `./scripts/start.ps1`로 빌드와 실행을 함께 할 수 있습니다. 키나 환경 변수를 수정한 경우 API와 worker를 모두 재시작합니다.

## 먼저 확인할 사용 흐름

1. **저장소 연결**에서 예시 저장소를 선택하거나 공개 GitHub URL과 본인의 아이디를 입력합니다. 개인·팀 프로젝트를 선택합니다.
2. **분석 범위**에서 외부 코드·자동 생성 코드 제외 후보와 담당 범위를 확인합니다. 분류와 담당은 보정할 수 있습니다.
3. **시스템 분석 시작**을 누릅니다. 기본값은 코드 구조 분석이며, 필요한 시스템에서 나중에 AI 설명을 요청할 수 있습니다.
4. **시스템 회고**의 왼쪽 목록에서 `Machine` 같은 시스템을 고르고 **AI 설명 생성**을 누릅니다. 상세 문단과 코드 근거를 확인합니다.
5. 문단 또는 시스템에 코멘트를 저장하고 반영할 코멘트를 선택합니다. **선택한 코멘트 반영**로 수정된 설명을 생성합니다. 이전 설명은 버전 목록에 남습니다.
6. 실제 담당·개발 의도를 확인한 설명을 검토 완료로 표시하고 **내보내기**에서 Markdown을 다운로드합니다. 초안을 포함하려면 미검토 설명 포함을 선택합니다.

화면 오른쪽 위 `?`에서도 사용 방법을 볼 수 있습니다. [로컬 확인 안내](docs/LOCAL_REVIEW.md)에 구체적인 예시가 있습니다.

## 구현한 기능

- 저장소 URL, GitHub 아이디, 개인·팀 설정. 브랜치/ref를 커밋 SHA로 고정한 분석.
- 공개 C# 파일 목록, 폴더·분류 검색, 분석 범위 및 파일별 담당 지정.
- Tree-sitter로 클래스·상속·필드·메서드 추출, 폴더를 기준으로 초기 시스템 구성.
- 선택된 범위 안에서 읽기 도구를 호출하는 Gemini 에이전트. 연결된 상세 문단과 코드 위치 제공.
- 코드 관찰·이력·사용자 설명·추정 구분. 근거 ID, 파일·줄 범위, 선택한 코멘트 버전 검증.
- 문단 코멘트, 코멘트 수정 이력, 설명 버전 보존, 검토 표시, 상세 내용의 Markdown 출력.
- 별도 프로세스의 DB 작업 큐. 진행 표시, 취소, 오류 안내, lease 만료 복구.
- 방문자별 작업 공간, CSRF 방어, 중복 요청 방지, 설정 충돌 검사, AI 호출·토큰 한도.
- 어두운 개발 도구형 화면, 데스크톱 3열 배치와 모바일 레이아웃.

## 구조와 코드 위치

화면 참고: [저장소 연결](docs/screenshots/01-connect-desktop.png), [구조 분석 작업 공간](docs/screenshots/03-workspace-desktop.png), [모바일 배치](docs/screenshots/05-workspace-mobile.png). 이 캡처는 구조 분석 단계의 검증 화면이며 실제 AI 생성 결과와 구분합니다.

React 화면이 FastAPI에 작업을 등록합니다. worker가 GitHub의 고정된 코드 버전을 읽어 구조와 AI 설명을 저장하고, 화면은 진행 상황과 결과를 조회합니다. 저장소 코드를 실행하거나 빌드하지 않습니다.

| 위치 | 역할 |
| --- | --- |
| `web/src/` | 연결, 분석 범위, 시스템·코멘트 작업 공간, 내보내기 |
| `server/app/main.py` | API, 세션·접근 검증, 정적 웹 제공 |
| `server/app/github.py` | URL 검증, 커밋 고정, 분류·수집, blob 검증 |
| `server/app/analysis.py` | C# 구문 분석, 시스템 초안, 심볼 관계 후보 |
| `server/app/agent.py` | 도구 등록·선택, 프롬프트, 근거·출력·예산 검증 |
| `server/app/providers.py` | Gemini 호환 API, 선택적 OpenAI 어댑터 |
| `server/app/models.py` | 프로젝트·설정·작업·코멘트·설명 버전 저장 |
| `server/worker.py` | 큐 실행, heartbeat, 취소·부분 완료·복구 |
| `server/launch.py` | 마이그레이션 후 API와 worker 실행 |
| `migrations/` | Alembic 스키마 변경 이력 |

에이전트는 `list_source_files`, `read_code`, `search_symbols`, `get_symbol_relations`, `get_file_history`, `get_attribution_evidence`, `get_review_context` 중 필요한 도구를 선택합니다. Gemini에는 최종 JSON을 제출하는 `submit_explanation`도 전달합니다. OpenAI Python SDK를 클라이언트로 사용하지만 기본 요청 목적지는 Google Gemini API입니다. OpenAI 유료 호출은 검증에 사용하지 않았으며 자동 대체도 하지 않습니다.

## 새 환경 설치

Node.js 24와 Python 3.12를 기준으로 확인했습니다. Anaconda에서는 프로젝트별 환경을 만든 뒤 같은 환경에 패키지를 설치합니다.

```powershell
conda env create --prefix ./.conda --file environment.yml
conda activate ./.conda
python -m pip install -r requirements.lock
python -m pip install -e ".[dev]"
Set-Location web
npm.cmd ci
npm.cmd run build
Set-Location ..
```

이미 `.env`가 있으면 덮어쓰지 않습니다. 없는 경우에만 `.env.example`을 복사하고 [Gemini 설정 안내](docs/GEMINI_SETUP.md)를 따릅니다. 키가 없거나 `AI_ENABLED=false`이면 구조 분석과 코멘트 저장만 사용할 수 있습니다.

프로젝트 루트에서 `python -m server.launch`를 실행합니다. 이 PC는 Windows 네이티브 모듈 실행 제한 때문에 별도 `.venv`로 검증했습니다. 보안 설정은 변경하지 않았습니다.

## 저장과 사용 한도

로컬 결과는 `data/code-retro.db`에 저장합니다. 작업 공간은 브라우저의 HttpOnly 쿠키와 연결되며 만료 기간은 기본 30일입니다. 쿠키 삭제·다른 브라우저·다른 기기에서 자동 복구는 아직 지원하지 않습니다. 필요한 결과를 Markdown으로 내보내세요. DB 백업 전에는 API와 worker를 종료합니다.

기본 분석 범위는 C# 최대 300개, 파일당 256 KiB, 총 5 MiB입니다. AI는 서버 전체 UTC 일별 200,000 토큰, 작업당 24회 모델 호출·80회 읽기 도구 호출을 제한합니다. 이 값은 앱의 상한이며 Gemini 무료 할당량을 보장하지 않습니다. 공급자 제한에 도달하면 오류를 표시하고 기존 자료를 유지합니다.

공개 운영 모드에서는 서버 전체 프로젝트 30개, DB 300 MiB 상한과 접속 주소별 요청 제한을 적용합니다. 상한에 도달하면 새 저장을 제한하며 기존 결과 조회·내보내기는 저장 용량 상황에 따라 제한될 수 있습니다. 만료된 세션의 데이터는 진행 중인 작업 종료 후 주기적으로 정리하고, 삭제한 프로젝트는 7일 후 영구 정리합니다. 무료 서비스이므로 별도 장기 백업은 제공하지 않으며 필요한 결과는 미리 내려받아야 합니다.

`.env`, 로컬 DB, 세션 쿠키가 있는 검증 파일은 Git에서 제외합니다. 공개 배포 상태는 [배포 메모](docs/DEPLOYMENT.md)에 있습니다.

## 확인한 결과

2026-09-17 기준:

- 자동 테스트 **SQLite 26개, PostgreSQL 27개 통과**. Ruff 및 TypeScript/Vite 빌드 통과. [GitHub Actions 실행 기록](https://github.com/gominsu08/code-retro/actions/runs/35171364895).
- 실제 공개 샘플의 프로젝트 코드 **112개 수집·분석**. 데스크톱·390px 모바일, 코멘트 저장, 새로고침 유지, 검토, Markdown 다운로드 흐름 통과.
- 실제 Gemini `gemini-3.5-flash-lite`로 Machine 설명 생성 및 코멘트를 반영한 후속 버전 저장 성공. 공개 서버에서 강조 요청 후 코드와 다른 추정을 내용 수정 코멘트로 정정하여 v4 본문 585자·2개 문단을 확인했습니다. 이전 v1~v3도 유지되며, 최종 Markdown은 3,824자입니다.
- SQLite·PostgreSQL 마이그레이션 및 스키마 차이 검사, Linux Docker 빌드·API/worker 상태 검사 통과.
- 무료 Render 웹 서비스와 Neon PostgreSQL 배포 성공. HTTPS·세션 보호, 샘플 112개 파일·30개 시스템, 원문 조회, 실제 AI 생성·코멘트 반영, 검토·Markdown 다운로드와 컨테이너 재배포 후 데이터 유지를 확인했습니다. 사용자가 다른 기기에서도 AI 설명 생성을 확인했습니다. 장시간 유휴 복귀는 추가 확인 대상입니다.

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check server tests migrations scripts
```

실제 GitHub UI 검증은 서버 실행 후 `web`에서 `$env:LIVE_GITHUB='1'`을 설정하고 `npx.cmd playwright test`로 실행합니다. Edge가 필요하며 검증용 프로젝트를 만듭니다. 기본 자동 테스트는 실제 AI를 호출하지 않습니다. 실제 Gemini 검증은 `python -m scripts.live_ai_verify --gemini`로 별도 실행하며, 앞선 UI 검증이 저장한 로컬 세션이 필요하고 API 할당량을 사용합니다.

## 현재 범위와 다음 작업

초기 시스템 분류는 폴더 중심 규칙입니다. 전체 프로젝트를 의미 기준으로 재분류하는 AI 단계는 아직 없습니다. C# 구문 분석은 Unity 실행이나 완전한 타입 해석을 대신하지 않습니다. 네임스페이스·스타일·최근 Git 이력은 담당 힌트이며 작성자나 인원수의 증명이 아닙니다.

근거 검증은 파일·줄·버전과 인용 형식을 확인합니다. 문장의 의미와 실제 개발 의도까지 자동으로 참임을 보장하지 않으므로 사용자 검토가 필요합니다. 비공개 저장소, 계정 로그인·기기 간 동기화, 장기 백업과 관리자 화면은 후속 범위입니다.

공개 배포와 다른 기기의 AI 생성 확인을 마쳤으며, 다음 단계는 제출 자료 정리입니다. 실사용 후기는 사용자가 직접 경험한 내용으로 작성합니다.

- [구현 명세서](IMPLEMENTATION_SPEC.md)
- [화면 설계](UI_DESIGN.md)
- [진행 상태·다음 세션 인계](docs/IMPLEMENTATION_STATUS.md)
- [개발 기록](docs/DEVELOPMENT_LOG.md)
