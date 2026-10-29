import { useEffect, useState } from 'react';
import './Dashboard.css';
import { sourceConfig } from '../data/mockData';
import { countSearchesSince, getRecentSearches } from '../utils/searchHistory';
import { apiFetch } from '../utils/apiClient';

const SYNC_MESSAGES = {
  started: '동기화를 시작했어요. 문서 수가 곧 올라갑니다.',
  already_running: '이미 동기화 중이에요.',
  no_accounts: '연동된 소스가 없어요. 사이드바에서 먼저 연결해 주세요.',
  error: '동기화를 시작하지 못했어요. 잠시 후 다시 시도해 주세요.',
};

const PROVIDER_LABELS = { google: 'Google Drive', github: 'GitHub', gitlab: 'GitLab', slack: 'Slack', notion: 'Notion' };

// 소스 하나의 진행 상태 → 막대 모양(value: 0~100 또는 null=전체 개수를 아직 모름)과 오른쪽 문구
function syncProgress(item) {
  if (item.status === 'error') return { state: 'error', value: 100, text: '실패' };
  if (item.status === 'done') {
    return { state: 'done', value: 100, text: item.lastCount > 0 ? `${item.lastCount}개 가져옴` : '최신 상태' };
  }
  if (item.phase === 'embedding' && item.total) {
    return { state: 'running', value: Math.round((item.done / item.total) * 100), text: `${item.done}/${item.total}` };
  }
  if (item.phase === 'queued') return { state: 'running', value: 0, text: '대기 중' };
  return { state: 'running', value: null, text: '문서 확인 중' };
}

export default function Dashboard({ onSearchTopic, onSyncNow, onRefreshStats, linkedCount, stats, user }) {
  const [recentSearches, setRecentSearches] = useState([]);
  const [searchesThisWeek, setSearchesThisWeek] = useState(0);
  const [syncing, setSyncing] = useState(false);
  const [syncMessage, setSyncMessage] = useState('');
  const [syncItems, setSyncItems] = useState([]);
  const [watching, setWatching] = useState(true);  // 처음 한 번은 이미 진행 중인 동기화가 있는지 확인

  // 동기화가 도는 동안 2초마다 소스별 진행 상황을 읽고, 문서 수도 같이 갱신한다.
  useEffect(() => {
    if (!watching) return undefined;
    let stopped = false;
    let statsTicks = 0;
    let emptyTicks = 0;  // 버튼 직후엔 서버가 아직 시작 전이라 목록이 비어 있을 수 있어 몇 번은 더 기다린다
    const tick = async () => {
      try {
        const data = await apiFetch('/api/v1/sync-status');
        if (stopped) return;
        const items = data?.items ?? [];
        setSyncItems(items);
        // 통계는 서버에서 비싼 집계라서 진행 조회(2초)마다 부르지 않고 ~20초마다만 새로 고친다
        statsTicks += 1;
        const running = items.some((i) => i.status === 'running');
        if (statsTicks % 10 === 1 || !running) onRefreshStats?.();
        emptyTicks = items.length === 0 ? emptyTicks + 1 : 0;
        const idle = items.length === 0 ? emptyTicks >= 8 : !items.some((i) => i.status === 'running');
        if (idle) setWatching(false);
      } catch {
        if (!stopped) setWatching(false);
      }
    };
    tick();
    const timer = setInterval(tick, 2000);
    return () => { stopped = true; clearInterval(timer); };
  }, [watching, onRefreshStats]);

  const handleSyncClick = async () => {
    setSyncing(true);
    setSyncMessage('');
    try {
      const res = await onSyncNow();
      setSyncMessage(SYNC_MESSAGES[res?.started ? 'started' : res?.reason] ?? SYNC_MESSAGES.error);
      if (res?.started || res?.reason === 'already_running') setWatching(true);
    } catch {
      setSyncMessage(SYNC_MESSAGES.error);
    } finally {
      setSyncing(false);
    }
  };

  useEffect(() => {
    getRecentSearches().then(setRecentSearches);
    countSearchesSince(7).then(setSearchesThisWeek);
  }, []);

  const totalDocuments = stats?.totalDocuments ?? 0;
  // 연동 직후엔 문서가 아직 0개라 stats.connectedSources(문서가 있는 소스 수)가 0이므로, 실제 연동 수를 쓴다
  const connectedSources = linkedCount ?? stats?.connectedSources ?? 0;
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
            <button
              className="dashboard__sync-button"
              onClick={handleSyncClick}
              disabled={syncing}
              title="새 문서는 15분마다 자동 반영돼요. 지금 바로 가져오려면 누르세요."
            >
              {syncing ? '요청 중...' : '🔄 지금 동기화'}
            </button>
          </div>
          {syncMessage && <p className="dashboard__sync-note">{syncMessage}</p>}
          {syncItems.some((i) => i.status === 'running') && (
            <p className="dashboard__sync-note dashboard__sync-note--first">
              💡 처음 연동할 때는 모든 문서를 가져오느라 시간이 오래 걸려요(문서가 많으면 수십 분).
              페이지를 닫아도 서버에서 계속 진행되고, 이후에는 바뀐 문서만 가져와서 훨씬 빨라요.
            </p>
          )}
          {syncItems.length > 0 && (
            <ul className="dashboard__sync-list">
              {syncItems.map((item) => {
                const p = syncProgress(item);
                return (
                  <li key={item.provider} className={`dashboard__sync-row dashboard__sync-row--${p.state}`}>
                    <div className="dashboard__sync-row-head">
                      <span>{PROVIDER_LABELS[item.provider] ?? item.provider}</span>
                      <span className="dashboard__sync-row-text">
                        {p.value !== null && p.state === 'running' ? `${p.value}% · ` : ''}{p.text}
                      </span>
                    </div>
                    <div
                      className="dashboard__progress"
                      role="progressbar"
                      aria-valuemin={0}
                      aria-valuemax={100}
                      aria-valuenow={p.value ?? undefined}
                    >
                      <div
                        className={`dashboard__progress-fill ${p.value === null ? 'dashboard__progress-fill--indeterminate' : ''}`}
                        style={p.value === null ? undefined : { width: `${p.value}%` }}
                      />
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
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
