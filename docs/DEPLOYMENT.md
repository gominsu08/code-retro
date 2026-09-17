# 공개 배포 운영 메모

2026-09-17: [GitHub 저장소](https://github.com/gominsu08/code-retro)의 코드를 Render Free 웹 서비스에 배포하고 Neon Free PostgreSQL과 Gemini를 연결했다. 공개 주소는 [code-retro-rxox.onrender.com](https://code-retro-rxox.onrender.com/)이다.

## 연결한 서비스

1. [Render](https://render.com/): Docker 기반 무료 웹 서비스, Ohio 지역, 수동 배포, `/api/health` 상태 검사.
2. [Neon](https://neon.com/): `code-retro` 프로젝트의 `production` 브랜치, PostgreSQL 18, Ohio 지역, Free 요금제. SSL 연결을 사용한다.
3. [gominsu08/code-retro](https://github.com/gominsu08/code-retro): 이 도구의 공개 소스 저장소. 분석 대상 Unity 저장소와 별개다.

DB 연결 문자열과 Gemini 키는 Render 환경 변수에만 설정한다. `.env`, `.runtime`, 로컬 DB, 세션 자료는 Git 및 Docker 빌드에서 제외한다. 키나 연결 문자열은 문서·커밋·대화에 기재하지 않는다. GitHub 조회 인증은 아직 연결하지 않았으므로 비로그인 API 한도가 적용된다.

공개 운영의 사용·저장 한도, PostgreSQL·컨테이너 검증과 서비스 설정을 완료했다. 유료 요금제나 도메인 구매는 포함하지 않는다.

## 준비한 구성

React 정적 파일, FastAPI와 별도 worker 프로세스를 하나의 Docker 컨테이너에서 실행한다. 저장소는 영속적인 PostgreSQL을 사용한다. 로컬 SQLite를 임시 컨테이너 파일 시스템에 두고 운영하지 않는다.

- `Dockerfile`: 웹 빌드 후 Python 서버에 결과를 복사한다. 일반 사용자 권한으로 실행한다.
- `render.yaml`: 무료 웹 서비스 1개, `/api/health`, 환경 변수 목록을 정의한다. 자동 배포는 끈다.
- `server.launch`: Alembic 적용 후 API와 worker를 실행한다. 어느 한쪽이 비정상 종료되면 컨테이너도 실패로 끝내 호스팅에서 복구할 수 있게 한다.
- Neon 무료 PostgreSQL에 마이그레이션을 적용했다. 컨테이너 재배포 후에도 저장 결과가 유지되는 것을 확인했다.

## 배포 환경 변수

| 변수 | 값 또는 설명 |
| --- | --- |
| `APP_ENV` | `production` |
| `PUBLIC_BASE_URL` | 실제 발급받은 HTTPS 서비스 주소 |
| `COOKIE_SECURE` | `true` |
| `DATABASE_URL` | Neon SSL PostgreSQL 연결 문자열. 비밀 설정으로 입력 |
| `AI_PROVIDER` | `gemini` |
| `AI_ENABLED` | `true` |
| `GEMINI_MODEL` | 현재 검증 모델 `gemini-3.5-flash-lite` |
| `GEMINI_API_KEY` | 서버 비밀 환경 변수. 브라우저·저장소에 넣지 않음 |
| `AI_DAILY_TOKEN_LIMIT` | 최초 설정 `200000` |
| `GLOBAL_JOB_LIMIT` | 무료 서버 초기 설정 `1` |
| `TRUST_PROXY_HEADERS` | Render 프록시에서 `true` |
| `GLOBAL_PROJECT_LIMIT` | 전체 `30`, 삭제 대기 자료도 포함 |
| `DATABASE_LIMIT_BYTES` | `314572800` (300 MiB) |

공개 서버에는 IP별 요청 제한, 1 MiB 요청 본문 제한, 저장 공간 검사, 만료 세션·삭제 프로젝트 정리와 worker heartbeat를 적용한다. 30일 동안 접속하지 않은 세션의 프로젝트와 삭제 후 7일 지난 프로젝트를 정리하며, 진행 중인 작업은 보호한다. 무료 Neon의 6시간 복원 이력은 장기 백업이 아니다. 사용자는 중요한 회고 결과를 Markdown으로 내려받아 별도로 보관한다.

## 무료 범위와 제약

Render 무료 웹 서비스는 일정 시간 방문이 없으면 중지되고 다음 접속 때 시작한다. 중지 중에는 worker도 실행되지 않으므로 항상 켜진 백그라운드 작업을 보장하지 않는다. 큐와 결과는 PostgreSQL에 남기며 복귀 시 lease 상태에 따라 복구한다. 임시 디스크는 보존 저장소가 아니다. [Render 무료 서비스 설명](https://render.com/docs/free).

Neon과 Gemini에도 무료 저장·연산·전송·요청 한도가 있다. 실제 배포 시점에 계정의 무료 요금과 한도를 다시 확인하며, 유료 전환이 필요하면 필요한 범위를 사용자에게 먼저 설명한다. [Neon 요금](https://neon.com/pricing), [Gemini 요금](https://ai.google.dev/gemini-api/docs/pricing).

## 추가 확인과 운영

1. 사용자가 다른 기기에서 AI 설명 생성을 확인했다. 해당 기기의 코멘트 반영·다운로드는 별도 확인 결과가 없으며, 이 두 기능은 개발 PC의 공개 URL에서 검증했다. 기기별 작업 공간은 서로 다르다.
2. 장시간 유휴 복귀와 진행 중 작업 중단 복구를 실서비스에서 추가 확인한다. 재배포 후 저장 결과 유지와 lease 복구 자동 검사는 통과했다.
3. 코드를 변경할 때 CI 통과 후 Render에서 수동 배포한다. 환경 변수 수정 후에는 `Save and deploy`로 반영한다.

## 확인한 배포 결과

- 서비스: [code-retro-rxox.onrender.com](https://code-retro-rxox.onrender.com/). Render Free 웹 서비스와 Neon Free PostgreSQL을 사용한다.
- 최초 배포에서 Linux Docker 빌드, PostgreSQL `0001` → `0002_public_operations` 마이그레이션과 API·worker 시작에 성공했다.
- GitHub 추가 인증 후 자동 검증을 게시했다. [CI 실행](https://github.com/gominsu08/code-retro/actions/runs/35170954970)에서 SQLite 26개, PostgreSQL 27개 테스트와 실제 Docker 컨테이너 검증이 모두 통과했다.
- `PUBLIC_BASE_URL`은 서비스 이름을 추측하지 않고 실제 발급된 HTTPS 주소와 정확히 일치해야 한다. 변경 후에는 환경 변수를 저장하고 재배포한다.
- 연결 풀을 재사용하도록 수정한 `43d8e81` 버전도 [CI](https://github.com/gominsu08/code-retro/actions/runs/35171364895)를 통과했으며 Render에 배포했다.
- 공개 브라우저에서 샘플 112개 파일·30개 시스템, Machine 원문 조회, 검증용 코멘트 저장과 검토 표시를 확인했다. Markdown 미리보기 14,008자와 실제 다운로드 파일을 확인했다.
- 위 자료를 저장한 뒤 컨테이너를 재배포했다. 같은 세션에서 프로젝트·코멘트·검토 상태가 보존되었다. 장시간 유휴 복귀와 진행 중 작업 중단 복구의 실서비스 검증은 별개로 남아 있다.
- HTTPS 세션 쿠키의 Secure·HttpOnly·SameSite와 외부 Origin 요청 거절을 확인했다.
- 현재 운영값은 `AI_ENABLED=true`이며 `GEMINI_API_KEY`를 서버 비밀 환경 변수로 설정했다. 실제 Gemini 호출과 공개 화면의 Machine v2 생성에 성공했다. 임시 배포용 비밀 파일은 제거했으며 키 값은 문서·Git에 남기지 않는다.
- 강조 코멘트를 반영한 v3에 이어, 코드와 다른 추정을 수정 요청한 v4도 성공했다. v4 본문 585자·2개 문단, 이전 설명 보존, 반영된 코멘트 표시와 코드 원문 연결을 확인했다. 검토 후 내보낸 Markdown은 미리보기·실제 파일 모두 3,824자이며 고정된 코드 URL 10개를 포함한다.
- 사용자가 같은 공개 주소를 다른 기기에서 열어 AI 설명 생성까지 완료했다고 확인했다. AI 내용의 의미 검토를 대체하는 검증은 아니며, 확인되지 않은 추정은 계속 사용자 검토 대상으로 표시한다.

화면만 공개되거나 로컬 서버만 동작하는 상태를 배포 완료로 기록하지 않는다.
