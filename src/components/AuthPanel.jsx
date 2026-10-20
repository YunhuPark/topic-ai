import { useState } from 'react';
import './AuthPanel.css';
import { saveSession } from '../utils/authStore';
import { API_BASE } from '../utils/apiClient';

export default function AuthPanel({ onAuthenticated, variant = 'sidebar' }) {
  const [mode, setMode] = useState('login'); // 'login' | 'signup'
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);

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
      setError('서버에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요.');
      setLoading(false);
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
      setLoading(false);
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
        >
          로그인
        </button>
        <button
          type="button"
          className={`auth-panel__tab ${mode === 'signup' ? 'auth-panel__tab--active' : ''}`}
          onClick={() => { setMode('signup'); setError(''); }}
        >
          회원가입
        </button>
      </div>
      <div className="auth-panel__field">
        <span className="auth-panel__field-icon" aria-hidden="true">📧</span>
        <input
          type="email"
          placeholder="이메일"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
          className="auth-panel__input"
        />
      </div>
      <div className="auth-panel__field">
        <span className="auth-panel__field-icon" aria-hidden="true">🔒</span>
        <input
          type="password"
          placeholder="비밀번호 (8자 이상)"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
          minLength={8}
          className="auth-panel__input"
        />
      </div>
      {error && <p className="auth-panel__error">{error}</p>}
      <button type="submit" disabled={loading} className="auth-panel__submit">
        <span>{loading ? '처리 중...' : mode === 'login' ? '로그인' : '가입하고 시작'}</span>
      </button>
    </form>
  );
}
