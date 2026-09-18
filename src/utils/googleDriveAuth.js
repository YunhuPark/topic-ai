// Google Drive 문서의 권한 인지형 검색을 위한 access token 보관소.
// 세션(탭) 단위로만 유지 — 새로고침해도 유지되지만 탭을 닫으면 사라진다 (OAuth access token은
// 수명이 짧고 민감하므로 검색 기록 등과 달리 localStorage 대신 sessionStorage를 쓴다).
const TOKEN_KEY = 'topicThreadAI.googleDriveToken';

export function saveGoogleDriveToken(token) {
  try {
    sessionStorage.setItem(TOKEN_KEY, token);
  } catch {
    // no-op
  }
}

export function getGoogleDriveToken() {
  try {
    return sessionStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function clearGoogleDriveToken() {
  try {
    sessionStorage.removeItem(TOKEN_KEY);
  } catch {
    // no-op
  }
}

export function getGoogleDriveHeader() {
  const token = getGoogleDriveToken();
  return token ? { 'X-Google-Drive-Token': token } : {};
}

const GIS_SCRIPT_SRC = 'https://accounts.google.com/gsi/client';
const DRIVE_SCOPE = 'https://www.googleapis.com/auth/drive.metadata.readonly email profile openid';

let gisLoadPromise = null;

function loadGoogleIdentityScript() {
  if (window.google?.accounts?.oauth2) return Promise.resolve();
  if (gisLoadPromise) return gisLoadPromise;

  gisLoadPromise = new Promise((resolve, reject) => {
    const script = document.createElement('script');
    script.src = GIS_SCRIPT_SRC;
    script.async = true;
    script.defer = true;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error('Google Identity Services 스크립트를 불러오지 못했습니다.'));
    document.head.appendChild(script);
  });
  return gisLoadPromise;
}

// Google 계정 연결(OAuth 동의) 후 access token을 반환한다. 사용자가 동의 창을 닫는 등
// 취소하면 onError로 알린다.
export async function requestGoogleDriveAccess(clientId) {
  await loadGoogleIdentityScript();

  return new Promise((resolve, reject) => {
    const client = window.google.accounts.oauth2.initTokenClient({
      client_id: clientId,
      scope: DRIVE_SCOPE,
      callback: (response) => {
        if (response.error) {
          reject(new Error(response.error_description || response.error));
          return;
        }
        resolve(response.access_token);
      },
      error_callback: (error) => {
        reject(new Error(error?.message || 'Google 인증이 취소되었습니다.'));
      },
    });
    client.requestAccessToken();
  });
}
