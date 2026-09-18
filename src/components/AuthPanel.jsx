import { useState } from 'react';
import './AuthPanel.css';
import { saveSession } from '../utils/authStore';

const API_BASE = 'http://localhost:8000';

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
    try {
      const res = await fetch(`${API_BASE}/api/v1/auth/${mode}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      });
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
      <input
        type="email"
        placeholder="이메일"
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        required
        className="auth-panel__input"
      />
      <input
        type="password"
        placeholder="비밀번호 (8자 이상)"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
        required
        minLength={8}
        className="auth-panel__input"
      />
      {error && <p className="auth-panel__error">{error}</p>}
      <button type="submit" disabled={loading} className="auth-panel__submit">
        {loading ? '처리 중...' : mode === 'login' ? '로그인' : '가입하고 시작'}
      </button>
    </form>
  );
}
