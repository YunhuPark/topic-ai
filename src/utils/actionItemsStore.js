// 할 일(액션아이템)도 검색 기록과 마찬가지로 브라우저가 아니라 계정(백엔드 DB)에 귀속된다.
// 저장 자체는 백엔드가 검색 시점에 자동으로 하므로, 여기서는 조회/상태토글/삭제만 담당한다.
// teamId를 주면 그 팀이 공유하는 할 일 리스트를, 안 주면(기본값) 개인 리스트를 읽고 쓴다.
import { apiFetch } from './apiClient';

// 백엔드는 snake_case(due_date)로 주는데 프론트는 다른 곳(dueDate 등)과 맞춰 camelCase로 쓴다.
function toCamelCase(record) {
  return {
    id: record.id,
    query: record.query,
    task: record.task,
    assignee: record.assignee,
    dueDate: record.due_date,
    status: record.status,
    source: record.source,
    savedAt: record.saved_at,
  };
}

export async function getAllActionItems(teamId) {
  const qs = teamId ? `?team_id=${teamId}` : '';
  const rows = await apiFetch(`/api/v1/action-items${qs}`);
  return rows.map(toCamelCase);
}

export async function toggleActionItemStatus(id, teamId) {
  const qs = teamId ? `?team_id=${teamId}` : '';
  const rows = await apiFetch(`/api/v1/action-items/${id}${qs}`, { method: 'PATCH' });
  return rows.map(toCamelCase);
}

export async function saveActionItem(query, item, teamId) {
  const rows = await apiFetch('/api/v1/action-items', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query, item, team_id: teamId ?? null }),
  });
  return rows.map(toCamelCase);
}

export async function deleteActionItem(id, teamId) {
  const qs = teamId ? `?team_id=${teamId}` : '';
  const rows = await apiFetch(`/api/v1/action-items/${id}${qs}`, { method: 'DELETE' });
  return rows.map(toCamelCase);
}
