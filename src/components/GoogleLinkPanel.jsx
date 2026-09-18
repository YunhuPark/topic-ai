import { useState } from 'react';
import './GoogleLinkPanel.css';
import { requestGoogleDriveAccess, saveGoogleDriveToken, getGoogleDriveToken } from '../utils/googleDriveAuth';
import { getAuthHeader } from '../utils/authStore';

const API_BASE = 'http://localhost:8000';
const CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID;

export default function GoogleLinkPanel({ linkedEmail, onLinked }) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  // "계정 연결(DB)"과 "이번 세션에서 검색에 쓸 access token(sessionStorage)"은 별개다 —
  // 로그아웃하거나 토큰이 만료되면 계정은 연결된 채로 있어도 이번 세션엔 토큰이 없을 수 있다.
  const hasSessionToken = Boolean(getGoogleDriveToken());

  const handleClick = async () => {
    setError('');
    if (!CLIENT_ID || CLIENT_ID === 'your_google_oauth_client_id_here') {
      setError('VITE_GOOGLE_CLIENT_ID가 설정되지 않았습니다.');
      return;
    }
    setLoading(true);
    try {
      const accessToken = await requestGoogleDriveAccess(CLIENT_ID);
      saveGoogleDriveToken(accessToken);

      const res = await fetch(`${API_BASE}/api/v1/auth/link/google`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...getAuthHeader() },
        body: JSON.stringify({ accessToken }),
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || 'Google 계정 연결에 실패했습니다.');
      }
      onLinked(data.provider_email);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="google-link">
      {linkedEmail && (
        <div className="google-link__status-row">
          <span className="google-link__status">{hasSessionToken ? '🟢' : '🟡'} Google 연결됨</span>
          <span className="google-link__email">{linkedEmail}</span>
        </div>
      )}
      <button className="google-link__button" onClick={handleClick} disabled={loading}>
        {loading
          ? '연결 중...'
          : linkedEmail
            ? (hasSessionToken ? '🔄 Drive 접근 다시 허용' : '⚠️ 이 세션에서 Drive 접근 허용하기')
            : '📁 Google Drive 연결'}
      </button>
      {!hasSessionToken && linkedEmail && (
        <p className="google-link__hint">
          계정은 연결돼 있지만, 로그아웃하거나 시간이 지나면 이번 세션에서 쓸 접근 권한이 사라져요.
          버튼을 눌러 다시 허용해야 Drive 문서가 검색됩니다.
        </p>
      )}
      {error && <p className="google-link__error">{error}</p>}
    </div>
  );
}
