// 동명이인 별칭 사전 — 사용자가 등록한 팀원 목록도 검색 기록/할 일과 마찬가지로
// 브라우저가 아니라 계정(백엔드 DB)에 귀속된다. teamId를 주면 그 팀 전체가 공유하는
// 사전을, 안 주면(기본값) 개인 사전을 읽고 쓴다.
import { apiFetch } from './apiClient';

function toCamelCase(record) {
  return {
    id: record.id,
    displayName: record.display_name,
    aliases: record.aliases,
    createdAt: record.created_at,
  };
}

export async function getAllPeople(teamId) {
  const qs = teamId ? `?team_id=${teamId}` : '';
  const rows = await apiFetch(`/api/v1/people${qs}`);
  return rows.map(toCamelCase);
}

export async function createPerson(displayName, aliases, teamId) {
  const rows = await apiFetch('/api/v1/people', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ display_name: displayName, aliases, team_id: teamId ?? null }),
  });
  return rows.map(toCamelCase);
}

export async function updatePerson(id, displayName, aliases, teamId) {
  const rows = await apiFetch(`/api/v1/people/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ display_name: displayName, aliases, team_id: teamId ?? null }),
  });
  return rows.map(toCamelCase);
}

export async function deletePerson(id, teamId) {
  const qs = teamId ? `?team_id=${teamId}` : '';
  const rows = await apiFetch(`/api/v1/people/${id}${qs}`, { method: 'DELETE' });
  return rows.map(toCamelCase);
}
