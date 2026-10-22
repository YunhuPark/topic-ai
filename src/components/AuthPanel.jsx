import { useState } from 'react';
import './AuthPanel.css';
import { saveSession } from '../utils/authStore';
import { API_BASE } from '../utils/apiClient';

// 느린 서버 기상(Render 무료 플랜은 비활동 시 슬립했다 첫 요청에서 깨어나는데 30~50초
// 걸릴 수 있음)을 "멈춘 것처럼 보이는" 상태와 구분해서 안내하기까지 기다리는 시간.
const SLOW_REQUEST_HINT_DELAY_MS = 5000;

export default function AuthPanel({ onAuthenticated, variant = 'sidebar' }) {
  const [mode, setMode] = useState('login'); // 'login' | 'signup'
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [slowHint, setSlowHint] = useState(false);
  const [showPassword, setShowPassword] = useState(false);

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
    </form>
  );
}
