import { useState } from 'react';
import './GoogleLinkPanel.css';
import { getAuthHeader } from '../utils/authStore';

const API_BASE = 'http://localhost:8000';
// Slack은 OAuth redirect URL로 "localhost"를 유효하지 않다고 거부해서 백엔드 콜백을
// 127.0.0.1로 등록했다 — 같은 로컬 서버지만 브라우저 입장에서는 다른 origin이라
// postMessage 발신처 검증 때 둘 다 허용해야 한다.
const TRUSTED_CALLBACK_ORIGINS = [new URL(API_BASE).origin, 'http://127.0.0.1:8000'];

// GitHub/GitLab 등 "클라이언트 시크릿이 필요한 표준 OAuth Authorization Code" 방식 계정 연결에
// 공용으로 쓰는 컴포넌트. 팝업을 띄우고 우리 백엔드 콜백이 끝나면 postMessage로 알려준다.
// access token은 서버(linked_accounts)에 저장되므로 매 세션 재동의가 필요 없다 (Google과 다른 점).
export default function PopupLinkPanel({ provider, displayName, icon, linkedLogin, onLinked }) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [syncing, setSyncing] = useState(false);
  const [syncCount, setSyncCount] = useState(null);

  // 연동 성공 직후 그 사람의 토큰으로 실제 볼 수 있는 저장소/프로젝트/채널/페이지 전체를
  // 자동으로 찾아 색인한다 — 관리자가 미리 지정해둔 고정 목록에만 의존하지 않도록.
  const syncNow = async () => {
    setSyncing(true);
    setSyncCount(null);
    try {
      const res = await fetch(`${API_BASE}/api/v1/sync/${provider}`, {
        method: 'POST',
        headers: getAuthHeader(),
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || '동기화에 실패했습니다.');
      }
      setSyncCount(data.count);
    } catch (err) {
      setError(err.message);
    } finally {
      setSyncing(false);
    }
  };

  const handleClick = async () => {
    setError('');
    setSyncCount(null);
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/v1/auth/link/${provider}/start`, {
        headers: getAuthHeader(),
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || `${displayName} 연결을 시작하지 못했습니다.`);
      }

      const popup = window.open(data.authorizeUrl, `${provider}-link`, 'width=600,height=700');
      if (!popup) {
        throw new Error('팝업이 차단되었습니다. 팝업 차단을 해제해주세요.');
      }

      await new Promise((resolve, reject) => {
        const handleMessage = (event) => {
          // 콜백 페이지는 우리 백엔드가 직접 그려서 보내므로, 발신 origin이 그 목록에 있어야 한다.
          if (!TRUSTED_CALLBACK_ORIGINS.includes(event.origin)) return;
          if (event.data?.provider !== provider) return;
          window.removeEventListener('message', handleMessage);
          if (event.data.ok) {
            onLinked(event.data.login);
            resolve();
          } else {
            reject(new Error(event.data.error || `${displayName} 연결에 실패했습니다.`));
          }
        };
        window.addEventListener('message', handleMessage);

        const checkClosed = setInterval(() => {
          if (popup.closed) {
            clearInterval(checkClosed);
            window.removeEventListener('message', handleMessage);
            reject(new Error('연결 창이 닫혔습니다.'));
          }
        }, 500);
      });
    } catch (err) {
      setError(err.message);
      setLoading(false);
      return;
    }
    setLoading(false);
    await syncNow();
  };

  return (
    <div className="google-link">
      {linkedLogin && (
        <div className="google-link__status-row">
          <span className="google-link__status">🟢 {displayName} 연결됨</span>
          <span className="google-link__email">@{linkedLogin}</span>
        </div>
      )}
      <button className="google-link__button" onClick={handleClick} disabled={loading || syncing}>
        {loading
          ? '연결 중...'
          : syncing
          ? '동기화 중...'
          : linkedLogin
          ? `🔄 ${displayName} 다시 연결`
          : `${icon} ${displayName} 연결`}
      </button>
      {syncCount !== null && !error && (
        <p className="google-link__hint">✅ 문서 {syncCount}개 동기화 완료</p>
      )}
      {error && <p className="google-link__error">{error}</p>}
    </div>
  );
}
