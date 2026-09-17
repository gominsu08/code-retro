let csrf = '';
export function setCsrf(value: string) { csrf = value; }
export class ApiError extends Error {
  code: string;
  constructor(message: string, code: string) { super(message); this.code = code; }
}
export async function api<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (method !== 'GET') { headers['X-CSRF-Token'] = csrf; headers['Idempotency-Key'] = crypto.randomUUID(); }
  let response: Response;
  try { response = await fetch(`/api/v1${path}`, { method, headers, credentials: 'same-origin', body: body === undefined ? undefined : JSON.stringify(body) }); }
  catch { throw new ApiError('서버에 연결하지 못했습니다. 연결 상태를 확인해주세요.', 'network'); }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new ApiError(data.error?.message || '요청을 처리하지 못했습니다.', data.error?.code || 'unknown');
  return data as T;
}
export function download(name: string, content: string) {
  const url = URL.createObjectURL(new Blob([content], { type: 'text/markdown;charset=utf-8' }));
  const a = document.createElement('a'); a.href = url; a.download = name; a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
