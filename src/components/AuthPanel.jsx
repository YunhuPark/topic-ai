import { useState } from 'react';
import './AuthPanel.css';
import { saveSession } from '../utils/authStore';
import { API_BASE } from '../utils/apiClient';

// 느린 서버 기상(Render 무료 플랜은 비활동 시 슬립했다 첫 요청에서 깨어나는데 30~50초
// 걸릴 수 있음)을 "멈춘 것처럼 보이는" 상태와 구분해서 안내하기까지 기다리는 시간.
const SLOW_REQUEST_HINT_DELAY_MS = 5000;

// PopupLinkPanel.jsx와 같은 이유 — Slack 등 일부 제공자가 콜백 리디렉션에 "localhost"를
// 거부해서 백엔드가 127.0.0.1로도 열릴 수 있다. 같은 로컬 서버지만 브라우저는 다른 origin으로
// 보므로 postMessage 발신처 검증 때 둘 다 허용해야 한다.
const TRUSTED_CALLBACK_ORIGINS = [new URL(API_BASE).origin, 'http://127.0.0.1:8000'];

export default function AuthPanel({ onAuthenticated, variant = 'sidebar' }) {
  const [mode, setMode] = useState('login'); // 'login' | 'signup'
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [slowHint, setSlowHint] = useState(false);
  const [showPassword, setShowPassword] = useState(false);

  // 이메일+비밀번호와 구분되는 별도 경로 — 성공/실패 모두 postMessage로 받아서, 성공 시
  // handleSubmit의 성공 처리(saveSession + onAuthenticated)와 동일하게 마무리한다.
  // Google/카카오 둘 다 서버 쪽 엔드포인트 이름(startPath)과 postMessage의 provider 값만
  // 다를 뿐 흐름이 완전히 같아서 하나로 묶었다.
  const handleSocialLogin = async (startPath, messageProvider, displayName, popupName) => {
    setError('');
    setLoading(true);
    setSlowHint(false);
    const slowTimer = setTimeout(() => setSlowHint(true), SLOW_REQUEST_HINT_DELAY_MS);

    try {
      const startRes = await fetch(`${API_BASE}${startPath}`);
      const startData = await startRes.json();
      if (!startRes.ok) throw new Error(startData.detail || `${displayName} 로그인을 시작하지 못했습니다.`);

      const popup = window.open(startData.authorizeUrl, popupName, 'width=500,height=650');
      if (!popup) {
        throw new Error('팝업이 차단되었습니다. 팝업 차단을 해제해주세요.');
      }

      await new Promise((resolve, reject) => {
        let settled = false;
        let checkClosed;
        const cleanup = () => {
          window.removeEventListener('message', handleMessage);
          clearInterval(checkClosed);
        };
        const handleMessage = (event) => {
          if (!TRUSTED_CALLBACK_ORIGINS.includes(event.origin)) return;
          if (event.data?.provider !== messageProvider) return;
          settled = true;
          cleanup();
          if (event.data.ok) {
            saveSession(event.data.token, event.data.email);
            onAuthenticated({ email: event.data.email });
            resolve();
          } else {
            reject(new Error(event.data.error || `${displayName} 로그인에 실패했습니다.`));
          }
        };
        window.addEventListener('message', handleMessage);
        checkClosed = setInterval(() => {
          if (popup.closed && !settled) {
            settled = true;
            cleanup();
            reject(new Error('로그인 창이 닫혔습니다.'));
          }
        }, 500);
      });
    } catch (err) {
      setError(err.message);
    } finally {
      clearTimeout(slowTimer);
      setLoading(false);
      setSlowHint(false);
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    setSlowHint(false);
    // 로딩이 이 시간보다 길어지면 "서버 깨우는 중" 안내를 띄운다 — 응답이 그보다 빨리
    // 오면 타이머가 정리되면서 안내 자체가 안 뜬다(평소 속도일 땐 방해 안 되게).
    const slowTimer = setTimeout(() => setSlowHint(true), SLOW_REQUEST_HINT_DELAY_MS);

    // fetch 자체가 실패(백엔드가 꺼져 있거나 네트워크 문제)하면 브라우저가 영어로
    // "Failed to fetch"를 던진다 — 나머지 화면은 전부 한글 오류 메시지를 쓰는데 여기만
    // 영어가 그대로 노출되던 문제를 따로 잡아서 한글로 바꾼다(apiClient.js의 apiFetch가
    // 이미 같은 패턴으로 처리하고 있는 것과 동일한 취지).
    let res;
    try {
      res = await fetch(`${API_BASE}/api/v1/auth/${mode}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      });
    } catch {
      clearTimeout(slowTimer);
      setError('서버에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요.');
      setLoading(false);
      setSlowHint(false);
      return;
    }

    try {
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || '요청에 실패했습니다.');
      }
      saveSession(data.token, data.email);
      onAuthenticated({ email: data.email });
    } catch (err) {
      setError(err.message);
    } finally {
      clearTimeout(slowTimer);
      setLoading(false);
      setSlowHint(false);
    }
  };

  return (
    <form className={`auth-panel auth-panel--${variant}`} onSubmit={handleSubmit}>
      <div className="auth-panel__tabs">
        <div className={`auth-panel__tab-indicator ${mode === 'signup' ? 'auth-panel__tab-indicator--right' : ''}`} />
        <button
          type="button"
          className={`auth-panel__tab ${mode === 'login' ? 'auth-panel__tab--active' : ''}`}
          onClick={() => { setMode('login'); setError(''); }}
          disabled={loading}
        >
          로그인
        </button>
        <button
          type="button"
          className={`auth-panel__tab ${mode === 'signup' ? 'auth-panel__tab--active' : ''}`}
          onClick={() => { setMode('signup'); setError(''); }}
          disabled={loading}
        >
          회원가입
        </button>
      </div>
      {/* 로그인/회원가입 두 폼이 필드 구성은 똑같아서 지금 어느 모드인지 헷갈린다는 피드백 —
          탭 색만으로는 부족해서, 지금 모드가 뭘 하는 중인지 짧게 문장으로 한 번 더 알려준다. */}
      <p className="auth-panel__mode-hint">
        {mode === 'login' ? '이미 계정이 있으신가요? 로그인해주세요.' : '처음이신가요? 이메일과 비밀번호로 새 계정을 만들어요.'}
      </p>
      <div className="auth-panel__field">
        <span className="auth-panel__field-icon" aria-hidden="true">📧</span>
        <input
          type="email"
          placeholder="이메일"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
          disabled={loading}
          className="auth-panel__input"
        />
      </div>
      <div className="auth-panel__field">
        <span className="auth-panel__field-icon" aria-hidden="true">🔒</span>
        <input
          type={showPassword ? 'text' : 'password'}
          placeholder="비밀번호 (8자 이상)"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
          minLength={8}
          disabled={loading}
          className="auth-panel__input auth-panel__input--password"
        />
        <button
          type="button"
          className="auth-panel__password-toggle"
          onClick={() => setShowPassword((v) => !v)}
          disabled={loading}
          aria-label={showPassword ? '비밀번호 숨기기' : '비밀번호 보기'}
          tabIndex={-1}
        >
          {showPassword ? '🙈' : '👁️'}
        </button>
      </div>
      {error && <p className="auth-panel__error">{error}</p>}
      {slowHint && (
        <p className="auth-panel__hint">
          서버를 깨우는 중이에요 — 한동안 사용이 없으면 잠시 쉬는 서버라, 처음 한 번은 최대
          1분 정도 걸릴 수 있어요.
        </p>
      )}
      <button type="submit" disabled={loading} className="auth-panel__submit">
        {loading && <span className="auth-panel__submit-spinner" aria-hidden="true" />}
        <span>{loading ? '처리 중...' : mode === 'login' ? '로그인' : '가입하고 시작'}</span>
      </button>
      <div className="auth-panel__divider">
        <span>또는</span>
      </div>
      <button
        type="button"
        className="auth-panel__google"
        onClick={() => handleSocialLogin('/api/v1/auth/google/start', 'google_login', 'Google', 'google-login')}
        disabled={loading}
      >
        <span className="auth-panel__google-icon" aria-hidden="true">G</span>
        Google로 계속하기
      </button>
      <button
        type="button"
        className="auth-panel__kakao"
        onClick={() => handleSocialLogin('/api/v1/auth/kakao/start', 'kakao_login', '카카오', 'kakao-login')}
        disabled={loading}
      >
        <span className="auth-panel__kakao-icon" aria-hidden="true">K</span>
        카카오로 계속하기
      </button>
    </form>
  );
}
