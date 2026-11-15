import { useEffect, useState } from 'react';
import './SearchView.css';
import './Dashboard.css';
import SearchBar from './SearchBar';
import TopicThread from './TopicThread';
import AISummaryPanel from './AISummaryPanel';
import { getRecentSearches } from '../utils/searchHistory';

function SearchLoadingSkeleton() {
  return (
    <div className="app__results search-view__skeleton animate-fade-in">
      <div className="app__results-left">
        {[1, 2, 3].map((i) => (
          <div key={i} className="skeleton-card">
            <div className="skeleton-block skeleton-block--title" />
            <div className="skeleton-block skeleton-block--line" />
            <div className="skeleton-block skeleton-block--line skeleton-block--short" />
            <div className="skeleton-block skeleton-block--tag" />
          </div>
        ))}
      </div>
      <div className="app__results-right glass-panel skeleton-summary">
        <div className="skeleton-block skeleton-block--badge" />
        <div className="skeleton-block skeleton-block--heading" />
        {[1, 2, 3, 4].map((i) => (
          <div key={i} className="skeleton-block skeleton-block--point" />
        ))}
      </div>
    </div>
  );
}

export default function SearchView({
  onSearch, isSearching, hasSearched, searchQuery, searchError,
  documents, summary, searchTiming, selectedDoc, onDocSelect, topics = [], teamId,
}) {
  const [recentSearches, setRecentSearches] = useState([]);
  // 검색창에 "지금 실제로 입력/표시 중인 글자" — SearchBar 로컬 state가 아니라 여기서 들고
  // 있어야, 홈의 "최근 검색" 카드를 눌렀을 때도 검색창에 바로 반영할 수 있다.
  const [query, setQuery] = useState('');

  useEffect(() => {
    getRecentSearches().then(setRecentSearches);
  }, [hasSearched]);

  // 실제로 검색을 실행하면서 검색창 글자도 그 검색어로 맞춘다 — 입력해서 제출하든, 주제
  // 카드를 클릭해서 바로 검색하든, 검색이 실행되는 모든 경로가 여기를 거치게 해서 "검색
  // 결과는 busan인데 검색창은 비어있다" 같은 불일치가 안 생기게 한다.
  const triggerSearch = (text) => {
    setQuery(text);
    onSearch(text);
  };

  // 오류가 났을 때는 초기 화면으로 되돌리지 않는다 — 이전 결과를 남겨두고 이유를 보여준다
  const showIdle = !hasSearched && !isSearching && !searchError;

  return (
    <div className="app__search-view">
      <div className={`app__search-header ${hasSearched ? 'app__search-header--compact' : ''}`}>
        {showIdle && (
          <div className="search-view__intro animate-fade-in-up">
            <h1 className="search-view__intro-title">무엇을 찾고 계신가요?</h1>
            <p className="search-view__intro-subtitle">
              Notion, Slack, Google Drive, GitHub, GitLab의 문서를 한 번에 검색하세요
            </p>
          </div>
        )}
        <SearchBar
          query={query}
          onQueryChange={setQuery}
          onSearch={triggerSearch}
          isSearching={isSearching}
          topics={topics}
        />
        {hasSearched && searchQuery && (
          <div className="app__search-query-info animate-fade-in">
            <span className="app__search-query-label">검색 결과:</span>
            <span className="app__search-query-text">"{searchQuery}"</span>
          </div>
        )}
        {searchError && (
          <div className="search-view__error animate-fade-in" role="alert">
            ⚠️ {searchError}
          </div>
        )}
      </div>

      {hasSearched && (
        <div className="app__results animate-fade-in-up">
          <div className="app__results-left">
            <TopicThread documents={documents} onDocSelect={onDocSelect} selectedDoc={selectedDoc} />
          </div>
          <div className="app__results-right glass-panel">
            <AISummaryPanel
              summary={summary}
              selectedDoc={selectedDoc}
              searchQuery={searchQuery}
              teamId={teamId}
              searchTiming={searchTiming}
            />
          </div>
        </div>
      )}

      {isSearching && <SearchLoadingSkeleton />}

      {/* 검색 전 빈 상태 — 그냥 비워두지 않고 최근 검색/추천 주제로 채운다 */}
      {showIdle && (
        <div className="search-view__idle animate-fade-in-up">
          <div className="dashboard__card glass-panel">
            <div className="dashboard__card-header">
              <h2 className="dashboard__card-title">🕐 최근 검색</h2>
            </div>
            <div className="dashboard__recent-list">
              {recentSearches.length === 0 && (
                <p className="dashboard__empty">아직 검색 기록이 없습니다. 위에서 첫 검색을 해보세요.</p>
              )}
              {recentSearches.slice(0, 6).map((item, i) => (
                // 검색창에서와 마찬가지로, 최근 검색어는 "검색창에 채우기만" — 바로 검색
                // 결과 화면으로 넘어가 버리면 다시 확인/수정할 틈이 없다는 피드백 반영.
                <button key={i} className="dashboard__recent-item" onClick={() => setQuery(item.query)}>
                  <span className="dashboard__recent-icon">↩</span>
                  <span className="dashboard__recent-query">{item.query}</span>
                  <span className="dashboard__recent-time">{item.time}</span>
                </button>
              ))}
            </div>
          </div>

          <div className="dashboard__card glass-panel">
            <div className="dashboard__card-header">
              <h2 className="dashboard__card-title">📄 추천 주제</h2>
            </div>
            <div className="dashboard__topics-grid">
              {topics.length === 0 && (
                <p className="dashboard__empty">아직 인덱싱된 문서가 없습니다.</p>
              )}
              {topics.slice(0, 6).map((topic) => (
                <button key={topic.id} className="dashboard__topic-card" onClick={() => triggerSearch(topic.label)}>
                  <div className="dashboard__topic-name">{topic.label}</div>
                  <div className="dashboard__topic-meta">
                    <span className="dashboard__topic-count">{topic.source}</span>
                    <span className="dashboard__topic-arrow">→</span>
                  </div>
                </button>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
