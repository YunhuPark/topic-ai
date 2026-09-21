import { useState, useCallback, useEffect } from 'react';
import './App.css';
import Sidebar from './components/Sidebar';
import SearchView from './components/SearchView';
import Dashboard from './components/Dashboard';
import AuthGate from './components/AuthGate';
import ActionItemsView from './components/ActionItemsView';
import { getToken, clearSession } from './utils/authStore';
import { apiFetch, setUnauthorizedHandler } from './utils/apiClient';

function App() {
  const [activeView, setActiveView] = useState('home');
  const [searchQuery, setSearchQuery] = useState('');
  const [isSearching, setIsSearching] = useState(false);
  const [hasSearched, setHasSearched] = useState(false);
  const [searchError, setSearchError] = useState('');
  const [selectedDoc, setSelectedDoc] = useState(null);
  const [documents, setDocuments] = useState([]);
  const [summary, setSummary] = useState(null);
  const [stats, setStats] = useState(null);
  const [user, setUser] = useState(null);
  const [sessionNotice, setSessionNotice] = useState('');
  const [googleLinkedEmail, setGoogleLinkedEmail] = useState(null);
  const [githubLinkedLogin, setGithubLinkedLogin] = useState(null);
  const [gitlabLinkedLogin, setGitlabLinkedLogin] = useState(null);
  const [slackLinkedLogin, setSlackLinkedLogin] = useState(null);
  const [notionLinkedLogin, setNotionLinkedLogin] = useState(null);
  const [sessionChecked, setSessionChecked] = useState(false);

  // 통계는 "내가 연동해서 가져온 문서"만 집계하므로 로그인한 뒤에만 의미가 있다 —
  // 그래서 마운트 시점이 아니라 세션이 확인된 뒤에 부른다.
  const fetchStats = useCallback(() => {
    if (!getToken()) return Promise.resolve(null);
    return apiFetch('/api/v1/stats')
      .then((data) => {
        if (data) setStats(data);
        return data;
      })
      .catch(() => null);
  }, []);

  const fetchLinkedAccounts = useCallback(() => {
    if (!getToken()) return Promise.resolve(null);
    return apiFetch('/api/v1/auth/linked')
      .then((accounts) => {
        const byProvider = (p) => accounts.find((a) => a.provider === p)?.provider_email ?? null;
        setGoogleLinkedEmail(byProvider('google'));
        setGithubLinkedLogin(byProvider('github'));
        setGitlabLinkedLogin(byProvider('gitlab'));
        setSlackLinkedLogin(byProvider('slack'));
        setNotionLinkedLogin(byProvider('notion'));
        return accounts;
      })
      .catch(() => null);
  }, []);

  const resetClientState = useCallback(() => {
    setUser(null);
    setStats(null);
    setDocuments([]);
    setSummary(null);
    setHasSearched(false);
    setSearchError('');
    setGoogleLinkedEmail(null);
    setGithubLinkedLogin(null);
    setGitlabLinkedLogin(null);
    setSlackLinkedLogin(null);
    setNotionLinkedLogin(null);
  }, []);

  // 어느 화면에서든 401이 오면(7일짜리 JWT 만료 등) 로그인 화면으로 돌려보내고 이유를 알려준다
  useEffect(() => {
    setUnauthorizedHandler((message) => {
      resetClientState();
      setSessionNotice(message);
    });
    return () => setUnauthorizedHandler(null);
  }, [resetClientState]);

  useEffect(() => {
    if (!getToken()) {
      setSessionChecked(true);
      return;
    }
    apiFetch('/api/v1/auth/me')
      .then((data) => {
        if (data) {
          setUser(data);
          fetchLinkedAccounts();
          fetchStats();
        }
      })
      .catch(() => {})
      .finally(() => setSessionChecked(true));
  }, [fetchLinkedAccounts, fetchStats]);

  const handleAuthenticated = useCallback((authedUser) => {
    setSessionNotice('');
    setUser(authedUser);
    fetchLinkedAccounts();
    fetchStats();
  }, [fetchLinkedAccounts, fetchStats]);

  const handleLogout = useCallback(() => {
    clearSession();
    resetClientState();
    setSessionNotice('');
  }, [resetClientState]);

  // 연동 직후에는 백그라운드 수집이 끝나는 대로 문서 수가 늘어난다 — 사용자가 F5를 누르지
  // 않아도 반영되도록, 연결 성공 후 잠시 동안 통계를 주기적으로 다시 불러온다.
  const pollStatsAfterLink = useCallback(() => {
    let tries = 0;
    const timer = setInterval(() => {
      tries += 1;
      fetchStats();
      if (tries >= 20) clearInterval(timer);  // 5초 × 20 = 약 100초
    }, 5000);
  }, [fetchStats]);

  // 연동 성공 시 공통 처리: 표시 이름 갱신 + 통계 즉시/주기적 재조회
  const afterLink = useCallback((setter, login) => {
    setter(login);
    fetchStats();
    pollStatsAfterLink();
  }, [fetchStats, pollStatsAfterLink]);

  const handleUnlinked = useCallback(() => {
    // 연동 해제 시 그 소스 문서도 서버에서 정리되므로 목록·통계를 모두 다시 읽는다
    fetchLinkedAccounts();
    fetchStats();
  }, [fetchLinkedAccounts, fetchStats]);

  const handleGoogleLinked = useCallback((login) => afterLink(setGoogleLinkedEmail, login), [afterLink]);
  const handleGithubLinked = useCallback((login) => afterLink(setGithubLinkedLogin, login), [afterLink]);
  const handleGitlabLinked = useCallback((login) => afterLink(setGitlabLinkedLogin, login), [afterLink]);
  const handleSlackLinked = useCallback((login) => afterLink(setSlackLinkedLogin, login), [afterLink]);
  const handleNotionLinked = useCallback((login) => afterLink(setNotionLinkedLogin, login), [afterLink]);

  const handleSearch = useCallback(async (query) => {
    setSearchQuery(query);
    setIsSearching(true);
    setSearchError('');
    setSelectedDoc(null);
    setActiveView('search');

    try {
      const data = await apiFetch(`/api/v1/search?q=${encodeURIComponent(query)}`);
      setDocuments(data.documents);
      setSummary(data.summary);
      setHasSearched(true);
      // 연동이 끊긴 소스가 있으면 결과가 조용히 비는 대신 재연결을 안내한다
      if (data.disconnectedSources?.length) {
        setSearchError(
          `${data.disconnectedSources.join(', ')} 연동이 만료되었거나 해제된 것 같습니다. ` +
          '사이드바 "연동 관리"에서 다시 연결해 주세요.'
        );
      } else if (data.degradedSources?.length) {
        setSearchError(
          `${data.degradedSources.join(', ')} 확인에 일시적으로 실패해서 일부 문서가 빠졌을 수 있습니다.`
        );
      }
    } catch (error) {
      // 예전엔 오류를 콘솔에만 찍고 화면을 초기 상태로 되돌려서, 서버가 꺼져 있어도
      // "검색 버튼이 안 눌린 것"처럼 보였다. 이제는 이유를 화면에 띄우고 이전 결과는 유지한다.
      console.error('Failed to fetch search results:', error);
      setSearchError(error.message || '검색에 실패했습니다.');
    } finally {
      setIsSearching(false);
    }
  }, []);

  const handleDocSelect = useCallback((doc) => {
    setSelectedDoc(doc);
  }, []);

  const renderMainContent = () => {
    if (activeView === 'actions') {
      return <ActionItemsView />;
    }

    if (activeView === 'search') {
      return (
        <SearchView
          onSearch={handleSearch}
          isSearching={isSearching}
          hasSearched={hasSearched}
          searchQuery={searchQuery}
          searchError={searchError}
          documents={documents}
          summary={summary}
          selectedDoc={selectedDoc}
          onDocSelect={handleDocSelect}
          topics={stats?.topics}
        />
      );
    }

    // 홈: 통계/최근 문서/최근 검색/지식 건강도를 가볍게 훑어보는 화면 (검색은 별도 메뉴)
    return <Dashboard onSearchTopic={handleSearch} stats={stats} user={user} />;
  };

  if (!sessionChecked) {
    return <div className="app" />;
  }

  if (!user) {
    return (
      <div className="app">
        <AuthGate onAuthenticated={handleAuthenticated} notice={sessionNotice} />
      </div>
    );
  }

  return (
    <div className="app">
      <Sidebar
        activeView={activeView}
        onViewChange={setActiveView}
        user={user}
        onLogout={handleLogout}
        onUnlinked={handleUnlinked}
        googleLinkedEmail={googleLinkedEmail}
        onGoogleLinked={handleGoogleLinked}
        githubLinkedLogin={githubLinkedLogin}
        onGithubLinked={handleGithubLinked}
        gitlabLinkedLogin={gitlabLinkedLogin}
        onGitlabLinked={handleGitlabLinked}
        slackLinkedLogin={slackLinkedLogin}
        onSlackLinked={handleSlackLinked}
        notionLinkedLogin={notionLinkedLogin}
        onNotionLinked={handleNotionLinked}
      />
      <main className="app__main">
        {renderMainContent()}
      </main>
    </div>
  );
}

export default App;
