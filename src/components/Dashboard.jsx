import { useEffect, useState } from 'react';
import './Dashboard.css';
import { sourceConfig } from '../data/mockData';
import { countSearchesSince, getRecentSearches } from '../utils/searchHistory';

export default function Dashboard({ onSearchTopic, stats, user }) {
  const [recentSearches, setRecentSearches] = useState([]);
  const [searchesThisWeek, setSearchesThisWeek] = useState(0);

  useEffect(() => {
    getRecentSearches().then(setRecentSearches);
    countSearchesSince(7).then(setSearchesThisWeek);
  }, []);

  const totalDocuments = stats?.totalDocuments ?? 0;
  const connectedSources = stats?.connectedSources ?? 0;
  const topics = stats?.topics ?? [];
  const freshness = stats?.freshness ?? { fresh: 0, moderate: 0, stale: 0 };
  const freshnessTotal = freshness.fresh + freshness.moderate + freshness.stale;
  const freshPercent = freshnessTotal > 0 ? Math.round((freshness.fresh / freshnessTotal) * 100) : 0;

  return (
    <div className="dashboard">
      {/* Welcome Hero */}
      <div className="dashboard__hero animate-fade-in-up">
        <div className="dashboard__hero-content">
          <div className="dashboard__hero-greeting">
            <span className="dashboard__hero-wave">👋</span>
            <h1 className="dashboard__hero-title">
              안녕하세요, <span className="gradient-text">{user?.email}</span>님
            </h1>
          </div>
          <p className="dashboard__hero-subtitle">
            오늘도 흩어진 지식을 하나로 연결해드릴게요
          </p>
        </div>
        <div className="dashboard__hero-stats">
          <div className="dashboard__stat">
            <span className="dashboard__stat-value gradient-text">{totalDocuments}</span>
            <span className="dashboard__stat-label">인덱싱 문서</span>
          </div>
          <div className="dashboard__stat">
            <span className="dashboard__stat-value gradient-text">{connectedSources}</span>
            <span className="dashboard__stat-label">연동 플랫폼</span>
          </div>
          <div className="dashboard__stat">
            <span className="dashboard__stat-value gradient-text">{searchesThisWeek}</span>
            <span className="dashboard__stat-label">이번 주 검색</span>
          </div>
        </div>
      </div>

      <div className="dashboard__grid">
        {/* Recent Searches */}
        <div className="dashboard__card glass-panel animate-fade-in-up delay-2">
          <div className="dashboard__card-header">
            <h2 className="dashboard__card-title">🕐 최근 검색</h2>
          </div>
          <div className="dashboard__recent-list">
            {recentSearches.length === 0 && (
              <p className="dashboard__empty">아직 검색 기록이 없습니다.</p>
            )}
            {recentSearches.slice(0, 5).map((item, i) => (
              <button
                key={i}
                className="dashboard__recent-item"
                onClick={() => onSearchTopic(item.query)}
              >
                <span className="dashboard__recent-icon">↩</span>
                <span className="dashboard__recent-query">{item.query}</span>
                <span className="dashboard__recent-time">{item.time}</span>
              </button>
            ))}
          </div>
        </div>

        {/* Recently Added */}
        <div className="dashboard__card glass-panel animate-fade-in-up delay-3">
          <div className="dashboard__card-header">
            <h2 className="dashboard__card-title">🔔 최근 추가된 문서</h2>
          </div>
          <div className="dashboard__notification-list">
            {topics.length === 0 && (
              <p className="dashboard__empty">아직 추가된 문서가 없습니다.</p>
            )}
            {topics.slice(0, 4).map((topic) => (
              <div key={topic.id} className="dashboard__notification">
                <div className="dashboard__notification-dot" />
                <div className="dashboard__notification-content">
                  <p className="dashboard__notification-message">
                    {sourceConfig[topic.source]?.label ?? topic.source} · {topic.label}
                  </p>
                  <span className="dashboard__notification-time">{topic.date}</span>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Knowledge Health — 한 줄 전체를 차지해서 위 두 카드와 균형을 맞춘다 */}
        <div className="dashboard__card dashboard__card--wide glass-panel animate-fade-in-up delay-4">
          <div className="dashboard__card-header">
            <h2 className="dashboard__card-title">📊 지식 건강도</h2>
          </div>
          <div className="dashboard__health">
            <div className="dashboard__health-ring">
              <svg viewBox="0 0 100 100" className="dashboard__health-svg">
                <circle cx="50" cy="50" r="42" fill="none" stroke="var(--bg-primary)" strokeWidth="8" />
                <circle
                  cx="50" cy="50" r="42" fill="none"
                  stroke="url(#healthGrad)"
                  strokeWidth="8"
                  strokeLinecap="round"
                  strokeDasharray={`${(freshPercent / 100) * 264} ${264}`}
                  transform="rotate(-90 50 50)"
                  className="dashboard__health-progress"
                />
                <defs>
                  <linearGradient id="healthGrad" x1="0%" y1="0%" x2="100%" y2="0%">
                    <stop offset="0%" stopColor="#0075de" />
                    <stop offset="100%" stopColor="#62aef0" />
                  </linearGradient>
                </defs>
              </svg>
              <div className="dashboard__health-value">
                <span className="dashboard__health-number gradient-text">{freshPercent}%</span>
                <span className="dashboard__health-label">최신</span>
              </div>
            </div>
            <div className="dashboard__health-breakdown">
              <div className="dashboard__health-item">
                <span className="dashboard__health-dot" style={{ background: 'var(--success)' }} />
                <span>최신 문서</span>
                <span className="dashboard__health-count">{freshness.fresh}개</span>
              </div>
              <div className="dashboard__health-item">
                <span className="dashboard__health-dot" style={{ background: 'var(--warning)' }} />
                <span>업데이트 필요</span>
                <span className="dashboard__health-count">{freshness.moderate}개</span>
              </div>
              <div className="dashboard__health-item">
                <span className="dashboard__health-dot" style={{ background: 'var(--danger)' }} />
                <span>오래된 문서</span>
                <span className="dashboard__health-count">{freshness.stale}개</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
