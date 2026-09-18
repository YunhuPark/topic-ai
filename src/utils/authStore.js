const TOKEN_KEY = 'topicThreadAI.authToken';
const EMAIL_KEY = 'topicThreadAI.authEmail';

export function saveSession(token, email) {
  try {
    localStorage.setItem(TOKEN_KEY, token);
    localStorage.setItem(EMAIL_KEY, email);
  } catch {
    // localStorage 접근 불가 시 조용히 무시
  }
}

export function clearSession() {
  try {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(EMAIL_KEY);
  } catch {
    // no-op
  }
}

export function getToken() {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function getAuthHeader() {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}
