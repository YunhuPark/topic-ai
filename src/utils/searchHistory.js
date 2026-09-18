// 검색 기록은 브라우저가 아니라 계정(백엔드 DB)에 귀속된다 — 검색 자체가 로그인 필수라
// 항상 getAuthHeader()가 유효한 상태에서 호출된다는 전제.
import { getAuthHeader } from './authStore';

const API_BASE = 'http://localhost:8000';

function formatRelativeTime(isoString) {
  const diffMs = Date.now() - new Date(isoString).getTime();
  const minutes = Math.floor(diffMs / 60000);
  if (minutes < 1) return '방금 전';
  if (minutes < 60) return `${minutes}분 전`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}시간 전`;
  const days = Math.floor(hours / 24);
  if (days === 1) return '어제';
  return `${days}일 전`;
}

export async function getRecentSearches() {
  try {
    const res = await fetch(`${API_BASE}/api/v1/search-history`, { headers: getAuthHeader() });
    if (!res.ok) return [];
    const rows = await res.json();
    return rows.map((r) => ({ query: r.query, time: formatRelativeTime(r.searched_at) }));
  } catch {
    return [];
  }
}

export async function countSearchesSince(days) {
  try {
    const res = await fetch(
      `${API_BASE}/api/v1/search-history/count?days=${days}`,
      { headers: getAuthHeader() }
    );
    if (!res.ok) return 0;
    const data = await res.json();
    return data.count;
  } catch {
    return 0;
  }
}
