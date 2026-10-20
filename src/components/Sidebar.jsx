import { useState, useEffect } from 'react';
import './Sidebar.css';
import PopupLinkPanel from './PopupLinkPanel';
import PeopleManager from './PeopleManager';
import TeamManager from './TeamManager';
import { getAllPeople } from '../utils/peopleStore';

const navItems = [
  { id: 'home', icon: '🏠', label: '홈' },
  { id: 'search', icon: '🔍', label: '검색' },
  { id: 'actions', icon: '⚡', label: '할 일 리스트' },
];

export default function Sidebar({
  activeView, onViewChange, user, onLogout, onUnlinked,
  googleLinkedEmail, onGoogleLinked,
  githubLinkedLogin, onGithubLinked,
  gitlabLinkedLogin, onGitlabLinked,
  slackLinkedLogin, onSlackLinked,
  notionLinkedLogin, onNotionLinked,
  currentTeamId, onTeamChange,
}) {
  const [collapsed, setCollapsed] = useState(false);
  const linkedCount = [googleLinkedEmail, githubLinkedLogin, gitlabLinkedLogin, slackLinkedLogin, notionLinkedLogin]
    .filter(Boolean).length;
  // 좁은 화면(폰)에서는 사이드바가 항상 켜져 있으면 본문을 다 가려버린다 — 평소엔 화면
  // 밖으로 숨겨두고, 왼쪽 위 햄버거 버튼으로 열고 닫는 오버레이 방식으로 전환한다(CSS
  // 미디어쿼리로 이 상태를 실제로 쓸지 말지 결정 — 넓은 화면에서는 이 state 자체가
  // 무시됨, Sidebar.css 참고).
  const [mobileOpen, setMobileOpen] = useState(false);
  // 모바일 드로어에서 메뉴 하나를 고르면 자동으로 닫아야 그 다음 화면이 바로 보인다.
  const handleViewChange = (view) => {
    onViewChange(view);
    setMobileOpen(false);
  };
  // 계정 연동 패널 5개(Google/GitHub/GitLab/Slack/Notion)는 평소엔 안 봐도 되는 정보라
  // 기본적으로 접어두고, 필요할 때만 펼친다 — 항상 펼쳐두면 사이드바가 지나치게 길어짐.
  const [accountsExpanded, setAccountsExpanded] = useState(false);
  // 한 번이라도 펼쳤으면 내용은 계속 DOM에 남겨둔다(닫혀도 사라지지 않음) — CSS 트랜지션으로
  // 펼침/접힘을 부드럽게 하려면 내용이 사라지는 순간에도 잠깐 DOM에 있어야 하기 때문.
  const [accountsMounted, setAccountsMounted] = useState(false);
  // 팀원 관리(동명이인 별칭 사전)도 같은 이유로 기본은 접어둔다.
  const [peopleExpanded, setPeopleExpanded] = useState(false);
  const [peopleMounted, setPeopleMounted] = useState(false);
  const [peopleCount, setPeopleCount] = useState(0);
  // "내 팀"(진짜 팀/조직 개념 — 별칭 사전인 "팀원 관리"와는 별개)도 같은 구조로 접어둔다.
  const [teamExpanded, setTeamExpanded] = useState(false);
  const [teamMounted, setTeamMounted] = useState(false);
  // 접힌 상태에서도 배지 숫자는 보여야 해서, 펼치기 전에 개수만 따로 한 번 가져온다.
  // currentTeamId가 바뀌면(팀 전환) 배지도 그 스코프 기준으로 다시 센다.
  useEffect(() => {
    getAllPeople(currentTeamId).then((rows) => setPeopleCount(rows.length)).catch(() => {});
  }, [currentTeamId]);

  const toggleAccounts = () => {
    setAccountsExpanded((v) => {
      if (!v) setAccountsMounted(true);
      return !v;
    });
  };
  const togglePeople = () => {
    setPeopleExpanded((v) => {
      if (!v) setPeopleMounted(true);
      return !v;
    });
  };
  const toggleTeam = () => {
    setTeamExpanded((v) => {
      if (!v) setTeamMounted(true);
      return !v;
    });
  };

  // 접혀있을 땐 "연동 관리"/"팀원 관리"/"내 팀"이 아예 안 보였다(전부 {!collapsed && ...}라
  // DOM에서 통째로 빠짐) — 그 상태에선 재확장하기 전엔 이 기능들에 접근할 방법이 없었다.
  // 접힌 동안에도 아이콘 하나씩은 보이게 하고, 누르면 사이드바를 펼치면서 그 섹션을 바로 열어준다.
  const openSectionExpanded = (which) => {
    setCollapsed(false);
    if (which === 'accounts') { setAccountsExpanded(true); setAccountsMounted(true); }
    if (which === 'people') { setPeopleExpanded(true); setPeopleMounted(true); }
    if (which === 'team') { setTeamExpanded(true); setTeamMounted(true); }
  };

  return (
    <>
      {/* 좁은 화면 전용 햄버거 버튼 — 넓은 화면에서는 Sidebar.css가 display:none으로 숨김 */}
      <button
        type="button"
        className="sidebar__mobile-toggle"
        onClick={() => setMobileOpen((v) => !v)}
        aria-label={mobileOpen ? '메뉴 닫기' : '메뉴 열기'}
      >
        <span className={`sidebar__mobile-toggle-icon ${mobileOpen ? 'sidebar__mobile-toggle-icon--open' : ''}`} />
      </button>
      {/* 드로어가 열려있을 때 뒤 배경을 어둡게 하고, 눌러서 닫을 수 있게 함 */}
      {mobileOpen && <div className="sidebar__mobile-backdrop" onClick={() => setMobileOpen(false)} />}

      <aside className={`sidebar ${collapsed ? 'sidebar--collapsed' : ''} ${mobileOpen ? 'sidebar--mobile-open' : ''}`}>
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
            onClick={() => handleViewChange(item.id)}
            title={item.label}
          >
            <span className="sidebar__nav-icon">{item.icon}</span>
            {/* 접힌 상태에서도 DOM에는 남겨두고 CSS로만 숨긴다 — hover 시 아이콘 옆으로
                슬라이드하며 나타나는 라벨 말풍선을 만들려면 실제로 렌더링돼 있어야 한다. */}
            <span className="sidebar__nav-label-text">{item.label}</span>
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

      {/* 사이드바를 접었을 때는 아래 세 섹션의 전체 아코디언 대신, 아이콘 하나씩만 보여준다
          (nav-item과 같은 클래스라 hover 시 라벨 말풍선도 똑같이 뜬다). 누르면 사이드바를
          펼치면서 그 섹션을 바로 열어준다. */}
      {collapsed && (
        <nav className="sidebar__collapsed-shortcuts">
          <button
            className="sidebar__nav-item"
            onClick={() => openSectionExpanded('accounts')}
            title="연동 관리"
          >
            <span className="sidebar__nav-icon">🔗</span>
            <span className="sidebar__nav-label-text">연동 관리</span>
          </button>
          <button
            className="sidebar__nav-item"
            onClick={() => openSectionExpanded('people')}
            title="팀원 관리"
          >
            <span className="sidebar__nav-icon">👥</span>
            <span className="sidebar__nav-label-text">팀원 관리</span>
          </button>
          <button
            className="sidebar__nav-item"
            onClick={() => openSectionExpanded('team')}
            title="내 팀"
          >
            <span className="sidebar__nav-icon">🏢</span>
            <span className="sidebar__nav-label-text">내 팀</span>
          </button>
        </nav>
      )}

      {/* 계정 연동 — 기본은 접힌 상태, 필요할 때만 펼침 */}
      {!collapsed && (
        <div className="sidebar__accounts">
          <button
            className="sidebar__accounts-toggle"
            onClick={toggleAccounts}
          >
            <span>연동 관리</span>
            <span className={`sidebar__accounts-count ${linkedCount === 5 ? 'sidebar__accounts-count--complete' : ''}`}>
              {linkedCount}/5
            </span>
            <span className={`sidebar__accounts-chevron ${accountsExpanded ? 'sidebar__accounts-chevron--open' : ''}`}>
              ›
            </span>
          </button>
          <div className={`sidebar__collapse sidebar__collapse--tall ${accountsExpanded ? 'sidebar__collapse--open' : ''}`}>
            <div className="sidebar__collapse-inner">
              {accountsMounted && (
                <div className="sidebar__accounts-list">
                  <PopupLinkPanel
                    provider="google" displayName="Google Drive" icon="📁"
                    linkedLogin={googleLinkedEmail} onLinked={onGoogleLinked} onUnlinked={onUnlinked}
                  />
                  <PopupLinkPanel
                    provider="github" displayName="GitHub" icon="🐙"
                    linkedLogin={githubLinkedLogin} onLinked={onGithubLinked} onUnlinked={onUnlinked}
                  />
                  <PopupLinkPanel
                    provider="gitlab" displayName="GitLab" icon="🦊"
                    linkedLogin={gitlabLinkedLogin} onLinked={onGitlabLinked} onUnlinked={onUnlinked}
                  />
                  <PopupLinkPanel
                    provider="slack" displayName="Slack" icon="💬"
                    linkedLogin={slackLinkedLogin} onLinked={onSlackLinked} onUnlinked={onUnlinked}
                  />
                  <PopupLinkPanel
                    provider="notion" displayName="Notion" icon="📓"
                    linkedLogin={notionLinkedLogin} onLinked={onNotionLinked} onUnlinked={onUnlinked}
                    note="⚠️ Notion은 새 페이지·데이터베이스를 만들 때마다 그 문서를 열어 '···' → 연결 추가로 직접 공유해야 검색에 나와요(Notion API 자체의 제약). 팀 문서용 상위 페이지 하나만 공유해두면, 그 아래 새로 만드는 문서는 자동으로 같이 공유됩니다."
                  />
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* 팀원 관리 (동명이인 별칭 사전) — 계정 연동과 같은 접고 펼치는 구조 */}
      {!collapsed && (
        <div className="sidebar__people">
          <button
            className="sidebar__people-toggle"
            onClick={togglePeople}
          >
            <span>팀원 관리</span>
            <span className="sidebar__people-count">{peopleCount}명</span>
            <span className={`sidebar__people-chevron ${peopleExpanded ? 'sidebar__people-chevron--open' : ''}`}>
              ›
            </span>
          </button>
          <div className={`sidebar__collapse ${peopleExpanded ? 'sidebar__collapse--open' : ''}`}>
            <div className="sidebar__collapse-inner">
              {peopleMounted && (
                <div className="sidebar__people-panel">
                  <PeopleManager onCountChange={setPeopleCount} teamId={currentTeamId} />
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* 내 팀 — 진짜 팀(조직) 관리. "팀원 관리"(별칭 사전)와 이름이 겹치지 않게 구분 */}
      {!collapsed && (
        <div className="sidebar__people">
          <button
            className="sidebar__people-toggle"
            onClick={toggleTeam}
          >
            <span>내 팀</span>
            <span className="sidebar__people-count">
              {currentTeamId ? '선택됨' : '개인'}
            </span>
            <span className={`sidebar__people-chevron ${teamExpanded ? 'sidebar__people-chevron--open' : ''}`}>
              ›
            </span>
          </button>
          <div className={`sidebar__collapse ${teamExpanded ? 'sidebar__collapse--open' : ''}`}>
            <div className="sidebar__collapse-inner">
              {teamMounted && (
                <div className="sidebar__people-panel">
                  <TeamManager currentTeamId={currentTeamId} onTeamChange={onTeamChange} currentUserId={user.id} />
                </div>
              )}
            </div>
          </div>
        </div>
      )}
      </aside>
    </>
  );
}
