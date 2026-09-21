// 검색 기록은 브라우저가 아니라 계정(백엔드 DB)에 귀속된다 — 검색 자체가 로그인 필수라
// 항상 유효한 세션에서 호출된다는 전제.
import { apiFetch } from './apiClient';

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

// 이 둘은 화면 한 켠의 보조 정보(최근 검색, 이번 주 검색 수)라, 실패해도 화면 전체를 막지 않고
// 빈 값으로 둔다. 단 401이면 apiFetch가 세션 만료 처리를 먼저 수행한다.
export async function getRecentSearches() {
  try {
    const rows = await apiFetch('/api/v1/search-history');
    return rows.map((r) => ({ query: r.query, time: formatRelativeTime(r.searched_at) }));
  } catch {
    return [];
  }
}

export async function countSearchesSince(days) {
  try {
    const data = await apiFetch(`/api/v1/search-history/count?days=${days}`);
    return data.count;
  } catch {
    return 0;
  }
}
