# 공개 배포 준비 메모

2026-09-17: 로컬 검토용 버전을 제공한 뒤 사용자가 **공개 배포 준비를 요청**했다. 현재 공개 URL은 없으며 계정 연결과 운영 검증을 준비한다.

## 지금 사용자에게 필요한 준비

1. [Render](https://render.com/) 무료 계정 가입·로그인. 웹 화면과 API를 실행할 서비스다.
2. [Neon](https://neon.com/) 무료 계정 가입·로그인. 분석 결과와 코멘트를 보관할 PostgreSQL 서비스다.
3. 이 도구의 새 GitHub 저장소 이름과 공개 여부 결정. 제안 이름은 `code-retro`이며 분석 대상 Unity 저장소와 별개다. GitHub CLI에는 `gominsu08` 계정이 연결되어 있다.

가입·이메일 인증·약관 동의는 사용자가 직접 진행한다. 기존 Gemini 키는 준비되어 있으므로 대화에 다시 전달할 필요가 없다. 이후 DB 연결 문자열과 키는 서비스의 비밀 환경 변수에 설정한다. GitHub 조회 한도를 완화할 읽기 전용 인증도 연결 단계에서 준비한다.

저장소 정리, 공개 운영의 사용·저장 한도 보완, PostgreSQL·컨테이너 검증, 서비스 설정 및 외부 접속 시험은 구현 작업으로 이어간다. 유료 요금제나 도메인 구매는 현재 준비에 포함하지 않는다.

## 준비한 구성

React 정적 파일, FastAPI와 별도 worker 프로세스를 하나의 Docker 컨테이너에서 실행한다. 저장소는 영속적인 PostgreSQL을 사용한다. 로컬 SQLite를 임시 컨테이너 파일 시스템에 두고 운영하지 않는다.

- `Dockerfile`: 웹 빌드 후 Python 서버에 결과를 복사한다. 일반 사용자 권한으로 실행한다.
- `render.yaml`: 무료 웹 서비스 1개, `/api/health`, 환경 변수 목록을 정의한다. 자동 배포는 끈다.
- `server.launch`: Alembic 적용 후 API와 worker를 실행한다. 어느 한쪽이 비정상 종료되면 컨테이너도 실패로 끝내 호스팅에서 복구할 수 있게 한다.
- DB 후보는 Neon 무료 PostgreSQL이다. 아직 계정을 연결하거나 DB를 생성하지 않았다.

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

## 무료 범위와 제약

Render 무료 웹 서비스는 일정 시간 방문이 없으면 중지되고 다음 접속 때 시작한다. 중지 중에는 worker도 실행되지 않으므로 항상 켜진 백그라운드 작업을 보장하지 않는다. 큐와 결과는 PostgreSQL에 남기며 복귀 시 lease 상태에 따라 복구한다. 임시 디스크는 보존 저장소가 아니다. [Render 무료 서비스 설명](https://render.com/docs/free).

Neon과 Gemini에도 무료 저장·연산·전송·요청 한도가 있다. 실제 배포 시점에 계정의 무료 요금과 한도를 다시 확인하며, 유료 전환이 필요하면 필요한 범위를 사용자에게 먼저 설명한다. [Neon 요금](https://neon.com/pricing), [Gemini 요금](https://ai.google.dev/gemini-api/docs/pricing).

## 실제 배포 전에 남은 작업

1. 사용자 로컬 검토 내용을 반영한다.
2. PostgreSQL에서 마이그레이션·잠금·취소·중복 방지를 검증하고 Linux Docker 빌드를 확인한다. 현재 PC에는 Docker가 없다.
3. 익명 공개 서비스의 IP 제한, 저장 용량 상한, 만료 자료 삭제, 백업 정책, worker 상태 관측을 보완한다.
4. 사용자가 무료 계정을 준비한 후 비밀이 제외된 코드를 배포한다. 가입·약관 동의는 사용자가 직접 한다.
5. 실제 HTTPS 주소로 새 브라우저 및 다른 기기에서 연결 → AI 생성 → 코멘트 수정 → 다운로드를 확인한다.
6. 재시작·유휴 복귀 후 저장과 작업 복구를 확인한 뒤 공개 URL과 운영 조건을 기록한다.

화면만 공개되거나 로컬 서버만 동작하는 상태를 배포 완료로 기록하지 않는다.
