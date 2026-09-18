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
  onSearch, isSearching, hasSearched, searchQuery,
  documents, summary, selectedDoc, onDocSelect, topics = [],
}) {
  const [recentSearches, setRecentSearches] = useState([]);

  useEffect(() => {
    getRecentSearches().then(setRecentSearches);
  }, [hasSearched]);

  const showIdle = !hasSearched && !isSearching;

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
        <SearchBar onSearch={onSearch} isSearching={isSearching} topics={topics} />
        {hasSearched && searchQuery && (
          <div className="app__search-query-info animate-fade-in">
            <span className="app__search-query-label">검색 결과:</span>
            <span className="app__search-query-text">"{searchQuery}"</span>
          </div>
        )}
      </div>

      {hasSearched && (
        <div className="app__results animate-fade-in-up">
          <div className="app__results-left">
            <TopicThread documents={documents} onDocSelect={onDocSelect} selectedDoc={selectedDoc} />
          </div>
          <div className="app__results-right glass-panel">
            <AISummaryPanel summary={summary} selectedDoc={selectedDoc} />
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
                <button key={i} className="dashboard__recent-item" onClick={() => onSearch(item.query)}>
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
                <button key={topic.id} className="dashboard__topic-card" onClick={() => onSearch(topic.label)}>
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
