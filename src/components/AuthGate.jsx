import './AuthModal.css';
import AuthPanel from './AuthPanel';

// 로그아웃 상태에서 앱 전체를 가리는 전체 화면 로그인 게이트.
// AuthModal과 카드 스타일은 같지만, 닫을 수 없고(뒤에 볼 앱이 없음) 페이지 자체다.
export default function AuthGate({ onAuthenticated }) {
  return (
    <div className="auth-modal__backdrop auth-gate">
      <div className="auth-modal__card glass-panel">
        <div className="auth-modal__header">
          <div className="auth-modal__logo">
            <svg width="32" height="32" viewBox="0 0 28 28" fill="none">
              <defs>
                <linearGradient id="authGateGrad" x1="0%" y1="0%" x2="100%" y2="100%">
                  <stop offset="0%" stopColor="#0075de" />
                  <stop offset="100%" stopColor="#62aef0" />
                </linearGradient>
              </defs>
              <path d="M14 2L4 8v12l10 6 10-6V8L14 2z" fill="url(#authGateGrad)" opacity="0.2" />
              <path d="M14 2L4 8v12l10 6 10-6V8L14 2z" stroke="url(#authGateGrad)" strokeWidth="1.5" fill="none" />
              <path d="M9 11h10M9 14h7M9 17h10" stroke="url(#authGateGrad)" strokeWidth="1.5" strokeLinecap="round" />
            </svg>
          </div>
          <h2 className="auth-modal__title gradient-text">TopicThread AI</h2>
          <p className="auth-modal__subtitle">
            흩어진 지식을 하나의 스레드로 — 로그인하고 시작하세요
          </p>
        </div>
        <AuthPanel onAuthenticated={onAuthenticated} variant="modal" />
      </div>
    </div>
  );
}
