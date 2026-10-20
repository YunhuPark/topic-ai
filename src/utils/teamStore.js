// "현재 선택된 팀"은 authStore.js와 같은 패턴(localStorage, 리액티브 스토어 아님) —
// 이 코드베이스에 Context/전역 스토어가 없어서, 기존 세션 관리 관례를 그대로 따른다.
import { apiFetch } from './apiClient';

const CURRENT_TEAM_KEY = 'topicThreadAI.currentTeamId';

export function getCurrentTeamId() {
  try {
    const raw = localStorage.getItem(CURRENT_TEAM_KEY);
    return raw ? Number(raw) : null;
  } catch {
    return null;
  }
}

export function setCurrentTeamId(id) {
  try {
    if (id == null) {
      localStorage.removeItem(CURRENT_TEAM_KEY);
    } else {
      localStorage.setItem(CURRENT_TEAM_KEY, String(id));
    }
  } catch {
    // localStorage 접근 불가 시 조용히 무시
  }
}

export async function getAllTeams() {
  return apiFetch('/api/v1/teams');
}

export async function createTeam(name) {
  return apiFetch('/api/v1/teams', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  });
}

export async function createInvite(teamId) {
  return apiFetch(`/api/v1/teams/${teamId}/invites`, { method: 'POST' });
}

export async function joinTeam(code) {
  return apiFetch('/api/v1/teams/join', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ code }),
  });
}

export async function getTeamMembers(teamId) {
  return apiFetch(`/api/v1/teams/${teamId}/members`);
}

export async function removeTeamMember(teamId, userId) {
  return apiFetch(`/api/v1/teams/${teamId}/members/${userId}`, { method: 'DELETE' });
}
