import { getAuthHeader, clearSession } from './authStore';

// 빌드 시점에 VITE_API_BASE를 넣어주면 그 값을 쓰고(배포용), 없으면 로컬 개발 기본값을 쓴다 —
// 예전엔 이 값이 하드코딩돼 있어서 localhost가 아닌 곳에 배포하려면 소스를 고쳐야 했다.
export const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000';

// 세션이 만료(401)되면 화면마다 따로 처리하는 대신 여기서 한 번에 처리한다 — 예전엔 각 fetch가
// 실패를 조용히 삼켜서, 토큰이 만료돼도 사이드바엔 이메일이 그대로 보이는데 연동은 0/5, 검색은
// 먹통, 할 일은 빈 목록인 "좀비 로그인" 상태가 됐다.
let onUnauthorized = null;

export function setUnauthorizedHandler(handler) {
  onUnauthorized = handler;
}

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

/**
 * 인증 헤더를 자동으로 붙이고, 실패를 삼키지 않고 던지는 fetch 래퍼.
 * 서버가 내려준 한국어 detail 메시지를 그대로 사용자에게 보여줄 수 있게 전달한다.
 */
export async function apiFetch(path, options = {}) {
  let response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...options,
      headers: { ...(options.headers || {}), ...getAuthHeader() },
    });
  } catch {
    // fetch 자체가 실패 = 서버가 꺼져 있거나 네트워크 문제
    throw new ApiError('서버에 연결할 수 없습니다. 백엔드가 실행 중인지 확인해 주세요.', 0);
  }

  if (response.status === 401) {
    clearSession();
    if (onUnauthorized) onUnauthorized('세션이 만료되었습니다. 다시 로그인해 주세요.');
    throw new ApiError('세션이 만료되었습니다. 다시 로그인해 주세요.', 401);
  }

  if (!response.ok) {
    let detail = `요청에 실패했습니다 (${response.status})`;
    try {
      const body = await response.json();
      if (body?.detail) detail = body.detail;
    } catch {
      // JSON이 아니면 기본 메시지 사용
    }
    throw new ApiError(detail, response.status);
  }

  if (response.status === 204) return null;
  return response.json();
}

// 검색 결과에서 문서 하나를 클릭했을 때 그 문서만 다시 요약한다 — 검색 시점 요약은
// 결과 전체(최대 4개)를 합친 것이라, 문서를 클릭해도 다른 문서 내용이 섞여 나왔다.
export async function summarizeDocument(query, document) {
  return apiFetch('/api/v1/summarize-document', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query, document }),
  });
}
