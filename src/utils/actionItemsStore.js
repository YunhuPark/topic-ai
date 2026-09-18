// 액션아이템도 검색 기록과 마찬가지로 브라우저가 아니라 계정(백엔드 DB)에 귀속된다.
// 저장 자체는 백엔드가 검색 시점에 자동으로 하므로, 여기서는 조회/상태토글만 담당한다.
import { getAuthHeader } from './authStore';

const API_BASE = 'http://localhost:8000';

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

export async function getAllActionItems() {
  try {
    const res = await fetch(`${API_BASE}/api/v1/action-items`, { headers: getAuthHeader() });
    if (!res.ok) return [];
    const rows = await res.json();
    return rows.map(toCamelCase);
  } catch {
    return [];
  }
}

export async function toggleActionItemStatus(id) {
  try {
    const res = await fetch(`${API_BASE}/api/v1/action-items/${id}`, {
      method: 'PATCH',
      headers: getAuthHeader(),
    });
    if (!res.ok) return [];
    const rows = await res.json();
    return rows.map(toCamelCase);
  } catch {
    return [];
  }
}
