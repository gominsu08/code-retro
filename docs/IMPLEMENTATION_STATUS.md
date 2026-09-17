# 구현 진행 기록

최종 갱신: 2026-09-17. **공개 서버·DB 배포 및 구조 분석 검증 완료, 공개 AI 키 적용 대기** 단계다. 서비스는 [code-retro-rxox.onrender.com](https://code-retro-rxox.onrender.com/)이다.

## 사용자 결정

- 공개 GitHub의 Unity/C# 프로젝트를 회고하고 포트폴리오 초안을 만든다. 예시 저장소는 `gominsu08/2025_Engine_TeamProject`, 본인 계정은 `gominsu08`이지만 웹 입력은 자유롭게 받는다.
- 어두운 개발 도구형 3열 화면을 사용한다. 구체적인 클래스·데이터·동작을 연결한 2~3개 이상의 상세 문단으로 설명한다.
- 코멘트를 선택하여 새 설명 버전을 만들고 이전 내용과 근거를 보존한다.
- 무료 운영을 우선하며 실제 AI는 Gemini 무료 API로 검증한다. OpenAI 유료 호출은 하지 않는다.
- 사용자가 `.env`에 키를 저장했으며 실제 생성과 코멘트 반영이 성공했다. 키를 출력하거나 문서·Git에 넣지 않는다.
- 최신 요청은 **“Render·Neon 가입 완료, 저장소는 code-retro 공개로”**다. `gominsu08/code-retro` 공개 저장소에 앱 코드를 게시했고 Render 무료 서비스와 Neon PostgreSQL 배포를 진행한다. 배포에는 추가 승인이 필요하지 않으며 유료 전환은 포함하지 않는다.

## 단계별 실제 상태

| 단계 | 상태 | 확인한 내용 |
| --- | --- | --- |
| M1 요구사항·UI | 로컬 구현 반영 | 상세 설명, 어두운 3열 화면, 반응형 구성 |
| M2 웹·저장·세션 | 로컬 검증 완료 | SQLite 저장, 세션 격리, CSRF, 설정 버전·중복 요청 검사 |
| M3 GitHub·C# 파싱 | 로컬 검증 완료 | 커밋 고정, C# 수집·blob 검증, Tree-sitter, 샘플 112개 수집 |
| M4 시스템·담당 | MVP 구현 | 폴더 기준 시스템, 구성 수정, 수동 담당, 네임스페이스·이력 힌트. 의미 기반 AI 재분류는 후속 |
| M5 도구 기반 AI | 실제 Gemini 검증 완료 | 읽기 도구 7개, 모델의 도구 선택, 상세 문단·근거·예산 검사 |
| M6 코멘트·버전·출력 | 로컬 검증 완료 | 코멘트 버전, 선택 반영, 이전 설명 보존, 검토·Markdown 다운로드 |
| M7 운영·배포 | 공개 서버 실행 / 전체 흐름 검증 중 | Render Free + Neon PostgreSQL, HTTPS·worker 정상. PostgreSQL 27개 테스트·Linux Docker 검증 통과 |

공개 서버는 현재 `AI_ENABLED=false`이며 Gemini 키를 저장하지 않았다. 사용자가 키 교체 완료를 알렸으나 지정한 `D:\Server_AI_Agent\.env`에는 이전 값이 남아 있어 실제 파일 저장을 다시 요청한 상태다. 키 값은 출력하지 않는다. `.runtime/key-rotation-reference.sha256`에는 이전 키의 비교용 해시만 있고 임시 배포용 비밀 파일은 제거했다.

## 실행 복구와 환경

`D:\Server_AI_Agent`에서 `.\.venv\Scripts\python.exe -m server.launch`를 실행한다. 사용자 주소는 `http://127.0.0.1:8000/`이다. 이미 실행 중인지 먼저 `/api/health`로 확인한다. 웹 변경 후에는 `web`에서 `npm.cmd run build`가 필요하다.

Python 3.12 전용 `.venv`와 Node.js 24를 사용한다. `.conda`도 있지만 이 PC의 Application Control이 일부 모듈을 차단하여 실제 검증은 `.venv`로 했다. Vite에는 지원되는 WASM 바인딩을 설치했다. 보안 정책은 변경하지 않았다.

Gemini 기본 모델은 `gemini-3.5-flash-lite`. `.env`와 `data/`는 Git 제외다. 브라우저 세션별로 프로젝트가 다르며 테스트 세션의 쿠키를 공유하지 않는다.

## 검증 근거

- 로컬 `pytest`: 26개 통과, PostgreSQL 전용 경쟁 테스트 1개는 건너뜀. 기존 검사에 IP 요청 한도, 용량 제한, 만료 자료 정리, chunked 요청 본문 제한을 추가했다.
- [GitHub Actions](https://github.com/gominsu08/code-retro/actions/runs/35170954970): Linux에서 SQLite 26개, PostgreSQL 27개 테스트 통과. PostgreSQL Alembic upgrade/check, Docker 빌드, 실제 컨테이너 API·worker 상태·정적 화면 검사 통과.
- Ruff 및 TypeScript/Vite 빌드 통과.
- 실제 저장소 UI 흐름: 분석, 코드 조회, 코멘트 저장, 검토, 새로고침 유지, Markdown 다운로드, 390px 가로 넘침 검사 통과.
- 실제 Gemini: Machine v2 생성 → 코멘트를 반영한 v3 성공. v3 본문 665자, 코드 인용 4개. 코멘트는 개발 의도를 지어내지 않는 강조 요청이었다.
- 로컬 자료: `.runtime/live-ai-verification.json`, `.runtime/machine-ai-retrospective.md`. 세션 정보가 있는 `web/.runtime/`는 공유·커밋하지 않는다.
- UI 캡처는 `web/test-results/`에 있다. 테스트는 사용자 실사용 후기가 아니다.
- 제출 참고용 구조 분석 화면 3장은 `docs/screenshots/`에도 복사했다. 실제 AI 결과는 별도 `.runtime` 문서로 구분한다.
- 재개 후 브라우저에서 GitHub 비로그인 API 한도가 확인되었다. 재조회는 취소하고 기존 수집 결과로 검토한다. 대기 작업 취소 시 오래된 재시도 안내를 지우도록 보완했다.
- 긴 구조 메모를 첫 AI 생성의 수정 문맥으로 불러와 한도를 초과하는 경우를 수정했다. 이후 사용자 브라우저에서 Machine v2의 실제 AI 생성이 성공했다. 첫 생성은 코드 본문을 읽고, 기존 AI 설명 수정만 이전 문단·근거를 재사용한다.
- 최종 390px 화면에서 도움말 버튼 노출과 가로 넘침 없음도 확인했다. 미리보기에는 Machine AI 설명을 열어두었다.
- SQLite Alembic upgrade/check 통과. 로컬 서버 재시작 후 저장 데이터 유지 확인. PostgreSQL 경쟁 상황은 CI에서 통과했으며 공개 서버의 재시작·유휴 복귀 검증은 이어서 진행한다.
- 공개 서버에서 샘플 112개 수집·30개 시스템, Machine 원문 조회, 검증용 코멘트 저장·검토와 Markdown 다운로드를 확인했다. 실제 파일과 미리보기는 14,008자로 일치했다. 컨테이너 재배포 뒤에도 코멘트와 검토 상태가 유지되었다.
- 파일 수집에서 작업별 HTTP 클라이언트를 공유하도록 개선했다. `43d8e81`의 [후속 CI](https://github.com/gominsu08/code-retro/actions/runs/35171364895)도 통과했고 Render에 배포했다. 수집 속도 개선율은 별도로 측정하지 않았다.

## 명세와의 차이 및 남은 범위

1. 시스템 분류는 폴더 중심 규칙이다. 심볼 관계는 이름 기반 후보이며 C# 의미 분석이나 Unity 실행 추적이 아니다.
2. 담당은 사용자가 지정한다. 스타일을 자동 군집화하여 참여자 수·인물을 추론하는 화면은 아직 없다.
3. 최신 분석의 시스템과 해당 설명 버전을 탐색한다. 과거 분석 실행 전체를 고르는 UI는 후속이다.
4. 저장한 코멘트는 보존하지만 저장 전 입력의 브라우저 종료 복구는 없다.
5. 근거 위치·ID와 형식은 검증한다. 문장 의미의 완전한 사실 검증은 제공하지 않는다.
6. 삭제 API는 작업 취소와 숨김 처리이며 7일 후 정리한다. 만료 세션 정리, IP별 제한, DB 용량 상한, worker heartbeat를 구현했다. 장기 자동 백업과 관리자 화면은 없다.
7. 공개 저장소는 생성·게시했다. 실제 AI를 포함한 공개 배포 검증·별도 기기 접속, 사용자 후기, 블로그·SNS 게시가 남아 있다.

## 다음 세션에서 할 일

[배포 메모](DEPLOYMENT.md)의 진행 상태를 이어서 처리한다. GitHub workflow 인증은 완료했으므로 다시 요청하지 않는다. Gemini 새 키의 실제 저장 여부를 값 출력 없이 확인하고 Render에 적용한 다음 공개 AI 생성·코멘트 반영을 검증한다. 사용자에게 같은 공개 주소를 휴대폰 등 별도 기기에서도 열어 전체 흐름을 확인하도록 안내한다. 이미 승인한 공개 배포·Gemini 무료 사용 방침을 다시 묻거나 유료 제공자로 자동 변경하지 않는다.
