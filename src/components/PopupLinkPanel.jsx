import { useState, useEffect, useRef } from 'react';
import './GoogleLinkPanel.css';
import { apiFetch, API_BASE } from '../utils/apiClient';

// Slack은 OAuth redirect URL로 "localhost"를 유효하지 않다고 거부해서 백엔드 콜백을
// 127.0.0.1로 등록했다 — 같은 로컬 서버지만 브라우저 입장에서는 다른 origin이라
// postMessage 발신처 검증 때 둘 다 허용해야 한다.
const TRUSTED_CALLBACK_ORIGINS = [new URL(API_BASE).origin, 'http://127.0.0.1:8000'];

// 5개 소스 전부 같은 팝업 + postMessage 패턴을 쓴다 (Google도 서버 사이드 OAuth로 바뀌면서
// 여기에 합류했다). 토큰은 서버에 저장되므로 매 세션 재동의가 필요 없다.
// 연동 직후 이 정도 시간 동안만 진행 상태를 폴링한다 — 그 뒤로도 안 끝나면 폴링을 접고
// 기존 안내 문구(가져오는 대로 문서 수가 올라간다)로 남겨둔다.
const SYNC_POLL_TIMEOUT_MS = 120_000;
const SYNC_POLL_INTERVAL_MS = 2_000;

export default function PopupLinkPanel({ provider, displayName, icon, linkedLogin, onLinked, onUnlinked }) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [justLinked, setJustLinked] = useState(false);
  const [unlinking, setUnlinking] = useState(false);
  const [syncInfo, setSyncInfo] = useState(null); // { status, lastCount, error } | null

  // 언마운트(사이드바 접기 등) 시 정리하기 위해 보관 — 예전엔 인터벌/리스너가 남아
  // "연결 중..."에 갇히거나 리스너가 새는 경우가 있었다.
  const cleanupRef = useRef(null);
  useEffect(() => () => cleanupRef.current?.(), []);

  // 연동 성공 직후 /api/v1/sync-status를 짧게 폴링해서 "가져오는 중"이라는 막연한 문구 대신
  // 실제로 몇 개를 가져왔는지/실패했는지 보여준다.
  useEffect(() => {
    if (!justLinked) return;
    let cancelled = false;
    const startedAt = Date.now();

    const poll = async () => {
      if (cancelled) return;
      try {
        const data = await apiFetch('/api/v1/sync-status');
        const mine = data.items.find((item) => item.provider === provider);
        if (mine && !cancelled) {
          setSyncInfo(mine);
          if (mine.status === 'done' || mine.status === 'error') return; // 폴링 종료
        }
      } catch {
        // 상태 조회 실패는 조용히 무시하고 다음 틱에 재시도 — 진행 상태 표시는 부가 기능이라
        // 이것 때문에 연동 자체가 실패한 것처럼 보이면 안 된다.
      }
      if (!cancelled && Date.now() - startedAt < SYNC_POLL_TIMEOUT_MS) {
        setTimeout(poll, SYNC_POLL_INTERVAL_MS);
      }
    };
    poll();

    return () => { cancelled = true; };
  }, [justLinked, provider]);

  const handleClick = async () => {
    setError('');
    setSyncInfo(null);
    setLoading(true);
    try {
      const data = await apiFetch(`/api/v1/auth/link/${provider}/start`);

      const popup = window.open(data.authorizeUrl, `${provider}-link`, 'width=600,height=700');
      if (!popup) {
        throw new Error('팝업이 차단되었습니다. 팝업 차단을 해제해주세요.');
      }

      await new Promise((resolve, reject) => {
        let settled = false;   // 성공 후 사용자가 팝업을 닫아도 실패로 처리하지 않도록
        let checkClosed;

        const cleanup = () => {
          window.removeEventListener('message', handleMessage);
          clearInterval(checkClosed);
          cleanupRef.current = null;
        };

        const handleMessage = (event) => {
          // 콜백 페이지는 우리 백엔드가 직접 그려서 보내므로, 발신 origin이 그 목록에 있어야 한다.
          if (!TRUSTED_CALLBACK_ORIGINS.includes(event.origin)) return;
          if (event.data?.provider !== provider) return;
          settled = true;
          cleanup();
          if (event.data.ok) {
            setJustLinked(true);
            onLinked(event.data.login);
            resolve();
          } else {
            reject(new Error(event.data.error || `${displayName} 연결에 실패했습니다.`));
          }
        };
        window.addEventListener('message', handleMessage);

        checkClosed = setInterval(() => {
          if (popup.closed && !settled) {
            settled = true;
            cleanup();
            reject(new Error('연결 창이 닫혔습니다.'));
          }
        }, 500);

        cleanupRef.current = cleanup;
      });
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleUnlink = async () => {
    setError('');
    setUnlinking(true);
    try {
      await apiFetch(`/api/v1/auth/link/${provider}`, { method: 'DELETE' });
      setJustLinked(false);
      onUnlinked?.(provider);
    } catch (err) {
      setError(err.message);
    } finally {
      setUnlinking(false);
    }
  };

  return (
    <div className="google-link">
      {linkedLogin && (
        <div className="google-link__status-row">
          <span className="google-link__status">🟢 {displayName} 연결됨</span>
          <span className="google-link__email">{linkedLogin}</span>
        </div>
      )}
      <button className="google-link__button" onClick={handleClick} disabled={loading || unlinking}>
        {loading ? '연결 중...' : linkedLogin ? `🔄 ${displayName} 다시 연결` : `${icon} ${displayName} 연결`}
      </button>
      {linkedLogin && (
        <button
          className="google-link__button google-link__button--secondary"
          onClick={handleUnlink}
          disabled={loading || unlinking}
        >
          {unlinking ? '해제 중...' : '연동 해제'}
        </button>
      )}
      {justLinked && syncInfo?.status === 'done' && (
        <p className="google-link__hint">
          ✅ 동기화 완료 — {syncInfo.lastCount > 0 ? `새 문서 ${syncInfo.lastCount}개를 가져왔어요.` : '가져온 문서 중 바뀐 내용은 없었어요.'}
        </p>
      )}
      {justLinked && syncInfo?.status === 'error' && (
        <p className="google-link__error">
          동기화 중 문제가 발생했어요: {syncInfo.error} (다음 자동 재동기화 때 다시 시도합니다)
        </p>
      )}
      {justLinked && (!syncInfo || syncInfo.status === 'running') && (
        <p className="google-link__hint">
          문서를 백그라운드에서 가져오는 중이에요 — 양이 많으면 몇 분 걸릴 수 있어요.
          가져오는 대로 홈 화면 문서 수가 자동으로 올라갑니다.
        </p>
      )}
      {error && <p className="google-link__error">{error}</p>}
    </div>
  );
}
