# Gemini 무료 API 연결

사용자 결정: 2026-09-17, Gemini 무료 API를 우선 사용한다. OpenAI 유료 검증은 실행하지 않는다.

1. [Google AI Studio의 API 키 페이지](https://aistudio.google.com/apikey)에서 무료 등급 프로젝트의 API 키를 준비한다.
2. 프로젝트 루트의 `.env` 파일에서 `GEMINI_API_KEY=` 오른쪽에 키를 붙여넣고 저장한다. 대화·GitHub·화면 캡처에 키를 넣지 않는다.
3. `AI_PROVIDER=gemini`, `GEMINI_MODEL=gemini-3.5-flash-lite`, `AI_ENABLED=true`를 사용한다.
4. 웹 서버와 작업 프로세스를 다시 시작한다. 상단의 `AI 연결됨` 표시를 확인한다.
5. 시스템을 하나 선택해 `AI 설명 생성`을 누른다. 설명의 코드 근거와 실제 담당 내용을 검토한다.

`.env`는 Git에서 제외되어 있다. 배포할 때는 동일한 값을 호스팅 서비스의 비밀 환경 변수에 입력한다. 키가 없으면 AI를 호출하지 않으며, 구조 분석과 코멘트 저장은 계속 사용할 수 있다.

무료 요청 한도는 계정·모델에 따라 달라진다. 무료 등급을 유지하려면 결제 계정을 연결하거나 유료 등급으로 전환하지 않는다. 이 앱은 유료 전환이나 다른 AI 제공자로의 자동 대체를 실행하지 않는다. 실제 무료 등급 여부는 Google AI Studio에서 확인해야 한다.

Google의 무료 API는 입력·출력을 제품 개선에 사용할 수 있다. 공개 코드라도 코멘트에 비밀 정보를 넣지 않는다. [요금·무료 등급 안내](https://ai.google.dev/gemini-api/docs/pricing), [데이터 이용 약관](https://ai.google.dev/gemini-api/terms#unpaid-services).

현재 검증 모델은 `gemini-3.5-flash-lite`다. 읽기 도구 7개와 최종 제출 함수로 설명을 받고 서버에서 JSON, 근거 ID, 코멘트 버전, 설명 분량을 다시 검증한다. 이전 설명의 코드 인용은 같은 스냅샷·파일·줄인지 재검증한 경우에만 유지한다. [공식 도구 호출 호환 API](https://ai.google.dev/gemini-api/docs/openai).

2026-09-17 이 PC에서 실제 코드 설명 생성과 선택한 코멘트를 반영한 후속 버전 저장을 확인했다. 설정 변경 후에는 API와 worker 두 프로세스를 함께 재시작해야 한다.
