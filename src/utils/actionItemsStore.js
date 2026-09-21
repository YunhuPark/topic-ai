// 할 일(액션아이템)도 검색 기록과 마찬가지로 브라우저가 아니라 계정(백엔드 DB)에 귀속된다.
// 저장 자체는 백엔드가 검색 시점에 자동으로 하므로, 여기서는 조회/상태토글/삭제만 담당한다.
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

// 실패를 빈 배열로 돌려주면 화면에서는 "할 일이 하나도 없다"와 구분이 안 된다 —
// 목록이 통째로 사라진 것처럼 보이므로, 오류는 그대로 던지고 화면에서 처리하게 한다.
export async function getAllActionItems() {
  const rows = await apiFetch('/api/v1/action-items');
  return rows.map(toCamelCase);
}

export async function toggleActionItemStatus(id) {
  const rows = await apiFetch(`/api/v1/action-items/${id}`, { method: 'PATCH' });
  return rows.map(toCamelCase);
}

export async function deleteActionItem(id) {
  const rows = await apiFetch(`/api/v1/action-items/${id}`, { method: 'DELETE' });
  return rows.map(toCamelCase);
}
