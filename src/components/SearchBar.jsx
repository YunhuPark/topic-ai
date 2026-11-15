import { useState, useEffect, useRef } from 'react';
import './SearchBar.css';
import { getRecentSearches } from '../utils/searchHistory';

// query/onQueryChange는 부모(SearchView)가 들고 있다 — 최근 검색어를 눌렀을 때 "검색창에
// 채우기만 하고 검색은 안 하기"를 하려면, 입력창 밖(홈 화면의 최근 검색 카드 등)에서도 같은
// 값을 건드릴 수 있어야 하기 때문이다(SearchBar 안에만 있는 로컬 state로는 불가능).
export default function SearchBar({ query, onQueryChange, onSearch, isSearching, topics = [] }) {
  const [isFocused, setIsFocused] = useState(false);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [recentSearches, setRecentSearches] = useState([]);
  const inputRef = useRef(null);

  useEffect(() => {
    const handleKeyDown = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        inputRef.current?.focus();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  const handleSubmit = (e) => {
    e.preventDefault();
    if (query.trim()) {
      onSearch(query);
      setShowSuggestions(false);
    }
  };

  const handleFocus = () => {
    setIsFocused(true);
    setShowSuggestions(true);
    getRecentSearches().then(setRecentSearches);
  };

  const handleBlur = () => {
    setTimeout(() => {
      setIsFocused(false);
      setShowSuggestions(false);
    }, 200);
  };

  // 최근 검색어는 "검색창에 채우기만" — 바로 검색까지 실행되면 결과를 확인하기도 전에
  // 화면이 바뀌어버린다는 피드백 반영. 주제 버블(아래)은 원래 하던 대로 클릭 즉시 검색한다.
  const handleRecentClick = (text) => {
    onQueryChange(text);
    setShowSuggestions(false);
  };

  const handleTopicBubbleClick = (text) => {
    onQueryChange(text);
    onSearch(text);
    setShowSuggestions(false);
  };

  return (
    <div className={`search-bar ${isFocused ? 'search-bar--focused' : ''}`}>
      <form onSubmit={handleSubmit} className="search-bar__form">
        <div className="search-bar__icon">
          {isSearching ? (
            <div className="search-bar__spinner" />
          ) : (
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="11" cy="11" r="8"/>
              <path d="M21 21l-4.35-4.35"/>
            </svg>
          )}
        </div>
        <input
          ref={inputRef}
          type="text"
          className="search-bar__input"
          placeholder="주제나 질문을 입력하세요... (예: 'Q3 마케팅 캠페인 관련 문서 모아줘')"
          value={query}
          onChange={(e) => onQueryChange(e.target.value)}
          onFocus={handleFocus}
          onBlur={handleBlur}
          id="main-search-input"
        />
        <div className="search-bar__shortcut">
          <kbd>Ctrl</kbd><kbd>K</kbd>
        </div>
        {query && (
          <button
            type="button"
            className="search-bar__clear"
            onClick={() => onQueryChange('')}
          >
            ✕
          </button>
        )}
        <button type="submit" className="search-bar__submit" disabled={!query.trim()}>
          검색
        </button>
      </form>

      {/* Suggestions Dropdown */}
      {showSuggestions && (
        <div className="search-bar__dropdown glass-panel animate-fade-in-up">
          {/* Recent Searches */}
          {recentSearches.length > 0 && (
            <div className="search-bar__section">
              <div className="search-bar__section-title">
                <span>🕐</span> 최근 검색
              </div>
              {recentSearches.map((item, i) => (
                <button
                  key={i}
                  className="search-bar__suggestion"
                  // 버튼을 누르는 순간(mousedown) 입력창이 blur되면서 열려있던 드롭다운이
                  // 클릭(click)보다 먼저 닫혀버려 클릭이 씹히는 경우가 있었다 — mousedown에서
                  // 기본 포커스 이동을 막아 입력창이 blur되지 않게 해서 클릭이 항상 먹히게 한다.
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={() => handleRecentClick(item.query)}
                >
                  <span className="search-bar__suggestion-icon">↩</span>
                  <span className="search-bar__suggestion-text">{item.query}</span>
                  <span className="search-bar__suggestion-time">{item.time}</span>
                </button>
              ))}
            </div>
          )}

          {/* Indexed Documents */}
          {topics.length > 0 && (
            <div className="search-bar__section">
              <div className="search-bar__section-title">
                <span>📄</span> 최근 인덱싱된 문서
              </div>
              <div className="search-bar__topics">
                {topics.slice(0, 6).map((topic) => (
                  <button
                    key={topic.id}
                    className="search-bar__topic-bubble"
                    onMouseDown={(e) => e.preventDefault()}
                    onClick={() => handleTopicBubbleClick(topic.label)}
                  >
                    {topic.label}
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
