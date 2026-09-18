import { useState, useCallback, useEffect } from 'react';
import './App.css';
import Sidebar from './components/Sidebar';
import SearchView from './components/SearchView';
import Dashboard from './components/Dashboard';
import AuthGate from './components/AuthGate';
import ActionItemsView from './components/ActionItemsView';
import { getAuthHeader, clearSession } from './utils/authStore';
import { getGoogleDriveHeader, clearGoogleDriveToken } from './utils/googleDriveAuth';

function App() {
  const [activeView, setActiveView] = useState('home');
  const [searchQuery, setSearchQuery] = useState('');
  const [isSearching, setIsSearching] = useState(false);
  const [hasSearched, setHasSearched] = useState(false);
  const [selectedDoc, setSelectedDoc] = useState(null);
  const [documents, setDocuments] = useState([]);
  const [summary, setSummary] = useState(null);
  const [stats, setStats] = useState(null);
  const [user, setUser] = useState(null);
  const [googleLinkedEmail, setGoogleLinkedEmail] = useState(null);
  const [githubLinkedLogin, setGithubLinkedLogin] = useState(null);
  const [gitlabLinkedLogin, setGitlabLinkedLogin] = useState(null);
  const [slackLinkedLogin, setSlackLinkedLogin] = useState(null);
  const [notionLinkedLogin, setNotionLinkedLogin] = useState(null);
  const [sessionChecked, setSessionChecked] = useState(false);

  useEffect(() => {
    fetch('http://localhost:8000/api/v1/stats')
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => data && setStats(data))
      .catch((error) => console.error('Failed to fetch stats:', error));
  }, []);

  const fetchLinkedAccounts = useCallback(() => {
    const authHeader = getAuthHeader();
    if (!authHeader.Authorization) return;
    fetch('http://localhost:8000/api/v1/auth/linked', { headers: authHeader })
      .then((res) => (res.ok ? res.json() : []))
      .then((accounts) => {
        const google = accounts.find((a) => a.provider === 'google');
        setGoogleLinkedEmail(google?.provider_email ?? null);
        const github = accounts.find((a) => a.provider === 'github');
        setGithubLinkedLogin(github?.provider_email ?? null);
        const gitlab = accounts.find((a) => a.provider === 'gitlab');
        setGitlabLinkedLogin(gitlab?.provider_email ?? null);
        const slack = accounts.find((a) => a.provider === 'slack');
        setSlackLinkedLogin(slack?.provider_email ?? null);
        const notion = accounts.find((a) => a.provider === 'notion');
        setNotionLinkedLogin(notion?.provider_email ?? null);
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    const authHeader = getAuthHeader();
    if (!authHeader.Authorization) {
      setSessionChecked(true);
      return;
    }
    fetch('http://localhost:8000/api/v1/auth/me', { headers: authHeader })
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (data) {
          setUser(data);
          fetchLinkedAccounts();
        }
      })
      .catch(() => {})
      .finally(() => setSessionChecked(true));
  }, [fetchLinkedAccounts]);

  const handleAuthenticated = useCallback((authedUser) => {
    setUser(authedUser);
    fetchLinkedAccounts();
  }, [fetchLinkedAccounts]);

  const handleLogout = useCallback(() => {
    clearSession();
    clearGoogleDriveToken();
    setUser(null);
    setGoogleLinkedEmail(null);
    setGithubLinkedLogin(null);
    setGitlabLinkedLogin(null);
    setSlackLinkedLogin(null);
    setNotionLinkedLogin(null);
  }, []);

  const handleGoogleLinked = useCallback((email) => {
    setGoogleLinkedEmail(email);
  }, []);

  const handleGithubLinked = useCallback((login) => {
    setGithubLinkedLogin(login);
  }, []);

  const handleGitlabLinked = useCallback((login) => {
    setGitlabLinkedLogin(login);
  }, []);

  const handleSlackLinked = useCallback((login) => {
    setSlackLinkedLogin(login);
  }, []);

  const handleNotionLinked = useCallback((login) => {
    setNotionLinkedLogin(login);
  }, []);

  const handleSearch = useCallback(async (query) => {
    setSearchQuery(query);
    setIsSearching(true);
    setHasSearched(false);
    setSelectedDoc(null);
    setActiveView('search');

    try {
      const response = await fetch(
        `http://localhost:8000/api/v1/search?q=${encodeURIComponent(query)}`,
        { headers: { ...getAuthHeader(), ...getGoogleDriveHeader() } }
      );
      if (!response.ok) {
        throw new Error('Search failed');
      }
      const data = await response.json();
      setDocuments(data.documents);
      setSummary(data.summary);
      setHasSearched(true);
      // 검색 기록/액션아이템 저장은 백엔드가 이 요청 안에서 계정에 귀속시켜 자동으로 처리한다.
    } catch (error) {
      console.error("Failed to fetch search results:", error);
      // Fallback for demo purposes if backend is down
      setHasSearched(false);
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
        <AuthGate onAuthenticated={handleAuthenticated} />
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
