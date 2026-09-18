import { useState, useEffect, useRef } from 'react';
import './SearchBar.css';
import { getRecentSearches } from '../utils/searchHistory';

export default function SearchBar({ onSearch, isSearching, topics = [] }) {
  const [query, setQuery] = useState('');
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

  const handleSuggestionClick = (text) => {
    setQuery(text);
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
          onChange={(e) => setQuery(e.target.value)}
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
            onClick={() => setQuery('')}
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
                  onClick={() => handleSuggestionClick(item.query)}
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
                    onClick={() => handleSuggestionClick(topic.label)}
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
