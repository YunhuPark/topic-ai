import { useState } from 'react';
import './Sidebar.css';
import GoogleLinkPanel from './GoogleLinkPanel';
import PopupLinkPanel from './PopupLinkPanel';

const navItems = [
  { id: 'home', icon: '🏠', label: '홈' },
  { id: 'search', icon: '🔍', label: '검색' },
  { id: 'actions', icon: '⚡', label: '액션 아이템' },
];

export default function Sidebar({
  activeView, onViewChange, user, onLogout,
  googleLinkedEmail, onGoogleLinked,
  githubLinkedLogin, onGithubLinked,
  gitlabLinkedLogin, onGitlabLinked,
  slackLinkedLogin, onSlackLinked,
  notionLinkedLogin, onNotionLinked,
}) {
  const [collapsed, setCollapsed] = useState(false);
  // 계정 연동 패널 5개(Google/GitHub/GitLab/Slack/Notion)는 평소엔 안 봐도 되는 정보라
  // 기본적으로 접어두고, 필요할 때만 펼친다 — 항상 펼쳐두면 사이드바가 지나치게 길어짐.
  const [accountsExpanded, setAccountsExpanded] = useState(false);

  return (
    <aside className={`sidebar ${collapsed ? 'sidebar--collapsed' : ''}`}>
      {/* Logo */}
      <div className="sidebar__logo" onClick={() => setCollapsed(!collapsed)}>
        <div className="sidebar__logo-icon">
          <svg width="28" height="28" viewBox="0 0 28 28" fill="none">
            <defs>
              <linearGradient id="logoGrad" x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%" stopColor="#0075de" />
                <stop offset="100%" stopColor="#62aef0" />
              </linearGradient>
            </defs>
            <path d="M14 2L4 8v12l10 6 10-6V8L14 2z" fill="url(#logoGrad)" opacity="0.2"/>
            <path d="M14 2L4 8v12l10 6 10-6V8L14 2z" stroke="url(#logoGrad)" strokeWidth="1.5" fill="none"/>
            <path d="M9 11h10M9 14h7M9 17h10" stroke="url(#logoGrad)" strokeWidth="1.5" strokeLinecap="round"/>
          </svg>
        </div>
        {!collapsed && (
          <div className="sidebar__logo-text">
            <span className="sidebar__logo-name gradient-text">TopicThread</span>
            <span className="sidebar__logo-version">AI v0.1</span>
          </div>
        )}
      </div>

      {/* Navigation */}
      <nav className="sidebar__nav">
        <div className="sidebar__nav-label">{!collapsed && '메뉴'}</div>
        {navItems.map((item) => (
          <button
            key={item.id}
            className={`sidebar__nav-item ${activeView === item.id ? 'sidebar__nav-item--active' : ''}`}
            onClick={() => onViewChange(item.id)}
            title={item.label}
          >
            <span className="sidebar__nav-icon">{item.icon}</span>
            {!collapsed && <span className="sidebar__nav-label-text">{item.label}</span>}
            {activeView === item.id && <div className="sidebar__nav-indicator" />}
          </button>
        ))}
      </nav>

      {/* User (Sidebar는 로그인 상태에서만 렌더링됨 — App.jsx의 AuthGate 참고) */}
      <div className="sidebar__user">
        <div className="sidebar__user-avatar">{user.email[0].toUpperCase()}</div>
        {!collapsed && (
          <div className="sidebar__user-info">
            <span className="sidebar__user-name">{user.email}</span>
            <span className="sidebar__user-role sidebar__user-logout" onClick={onLogout}>
              로그아웃
            </span>
          </div>
        )}
      </div>

      {/* 계정 연동 — 기본은 접힌 상태, 필요할 때만 펼침 */}
      {!collapsed && (
        <div className="sidebar__accounts">
          <button
            className="sidebar__accounts-toggle"
            onClick={() => setAccountsExpanded((v) => !v)}
          >
            <span>연동 관리</span>
            <span className="sidebar__accounts-count">
              {[googleLinkedEmail, githubLinkedLogin, gitlabLinkedLogin, slackLinkedLogin, notionLinkedLogin]
                .filter(Boolean).length}/5
            </span>
            <span className={`sidebar__accounts-chevron ${accountsExpanded ? 'sidebar__accounts-chevron--open' : ''}`}>
              ›
            </span>
          </button>
          {accountsExpanded && (
            <div className="sidebar__accounts-list">
              <GoogleLinkPanel linkedEmail={googleLinkedEmail} onLinked={onGoogleLinked} />
              <PopupLinkPanel
                provider="github" displayName="GitHub" icon="🐙"
                linkedLogin={githubLinkedLogin} onLinked={onGithubLinked}
              />
              <PopupLinkPanel
                provider="gitlab" displayName="GitLab" icon="🦊"
                linkedLogin={gitlabLinkedLogin} onLinked={onGitlabLinked}
              />
              <PopupLinkPanel
                provider="slack" displayName="Slack" icon="💬"
                linkedLogin={slackLinkedLogin} onLinked={onSlackLinked}
              />
              <PopupLinkPanel
                provider="notion" displayName="Notion" icon="📓"
                linkedLogin={notionLinkedLogin} onLinked={onNotionLinked}
              />
            </div>
          )}
        </div>
      )}
    </aside>
  );
}
