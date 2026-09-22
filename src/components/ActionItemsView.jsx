import { useEffect, useState } from 'react';
import './Dashboard.css';
import './AISummaryPanel.css';
import { getSourceMeta } from '../data/mockData';
import { getAllActionItems, toggleActionItemStatus, deleteActionItem } from '../utils/actionItemsStore';

export default function ActionItemsView() {
  const [items, setItems] = useState([]);
  const [error, setError] = useState('');
  // 기본을 '전체'로 둔다 — '진행 중'을 기본으로 뒀더니, 체크하는 순간 그 항목이 목록에서
  // 바로 사라져서(완료 탭으로 넘어가서) 사용자가 "체크가 됐는지 안 됐는지" 헷갈려했다.
  // '전체'가 기본이면 체크한 항목이 같은 화면에 취소선 처리로 남아서 바로 눈에 보인다.
  const [filter, setFilter] = useState('all'); // 'all' | 'open' | 'completed'

  useEffect(() => {
    getAllActionItems()
      .then(setItems)
      .catch((e) => setError(e.message));
  }, []);

  // 실패해도 목록을 비우지 않는다 — 예전엔 오류 시 빈 배열을 넣어서, 한 번의 네트워크 오류로
  // 할 일이 전부 사라진 것처럼 보였다.
  const handleToggle = (id) => {
    setError('');
    toggleActionItemStatus(id).then(setItems).catch((e) => setError(e.message));
  };

  const handleDelete = (id) => {
    setError('');
    deleteActionItem(id).then(setItems).catch((e) => setError(e.message));
  };

  const openCount = items.filter((i) => i.status !== 'completed').length;
  const completedCount = items.length - openCount;
  const tabs = [
    { id: 'all', label: '전체', count: items.length },
    { id: 'open', label: '진행 중', count: openCount },
    { id: 'completed', label: '완료', count: completedCount },
  ];
  const visibleItems = items.filter((i) => {
    if (filter === 'open') return i.status !== 'completed';
    if (filter === 'completed') return i.status === 'completed';
    return true;
  });

  return (
    <div className="dashboard">
      <div className="dashboard__hero animate-fade-in-up">
        <div className="dashboard__hero-content">
          <div className="dashboard__hero-greeting">
            <span className="dashboard__hero-wave">⚡</span>
            <h1 className="dashboard__hero-title">
              <span className="gradient-text">할 일 리스트</span>
            </h1>
          </div>
          <p className="dashboard__hero-subtitle">
            검색 결과에서 직접 고른 할 일을 체크박스 하나로 관리하세요
          </p>
        </div>
      </div>

      <div className="dashboard__card glass-panel animate-fade-in-up delay-2">
        <div className="dashboard__card-header">
          <h2 className="dashboard__card-title">할 일 리스트</h2>
          <span className="dashboard__card-badge">{openCount}개 진행 중</span>
        </div>
        {items.length > 0 && (
          <div className="action-items__tabs">
            {tabs.map((tab) => (
              <button
                key={tab.id}
                className={`action-items__tab ${filter === tab.id ? 'action-items__tab--active' : ''}`}
                onClick={() => setFilter(tab.id)}
              >
                {tab.label}
                <span className="action-items__tab-count">{tab.count}</span>
              </button>
            ))}
          </div>
        )}
        {error && <p className="dashboard__empty" role="alert">⚠️ {error}</p>}
        <div className="ai-panel__action-list">
          {items.length === 0 && !error && (
            <p className="dashboard__empty">
              아직 할 일이 없습니다. 검색 결과의 "할 일 리스트" 탭에서 "+ 추가"를 누르면 여기 쌓입니다.
            </p>
          )}
          {items.length > 0 && visibleItems.length === 0 && (
            <p className="dashboard__empty">
              {filter === 'completed' ? '완료한 할 일이 아직 없습니다.' : '진행 중인 할 일이 없습니다.'}
            </p>
          )}
          {visibleItems.map((item) => {
            const source = getSourceMeta(item.source);
            const isDone = item.status === 'completed';
            return (
              <div key={item.id} className="ai-panel__action-item">
                <button
                  className={`action-items__checkbox ${isDone ? 'action-items__checkbox--checked' : ''}`}
                  onClick={() => handleToggle(item.id)}
                  title={isDone ? '완료 취소' : '완료로 표시'}
                  aria-label={isDone ? '완료 취소' : '완료로 표시'}
                >
                  {isDone && '✓'}
                </button>
                <div className={`ai-panel__action-content ${isDone ? 'action-items__content--done' : ''}`}>
                  <div className="ai-panel__action-task">
                    {item.task}
                    {item.status === 'in-progress' && !isDone && (
                      <span className="action-items__inprogress-badge">진행 중</span>
                    )}
                  </div>
                  <div className="ai-panel__action-meta">
                    <span>👤 {item.assignee}</span>
                    <span>📅 {item.dueDate}</span>
                    <span>🔍 "{item.query}"</span>
                  </div>
                </div>
                {source && (
                  <span
                    className="ai-panel__action-source-badge"
                    style={{ background: source.bg, color: source.color }}
                  >
                    {source.icon}
                  </span>
                )}
                <button
                  className="ai-panel__action-delete"
                  onClick={() => handleDelete(item.id)}
                  title="이 할 일 삭제"
                  aria-label="이 할 일 삭제"
                >
                  ✕
                </button>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
