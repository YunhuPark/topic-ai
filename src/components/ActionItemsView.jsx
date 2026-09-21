import { useEffect, useState } from 'react';
import './Dashboard.css';
import './AISummaryPanel.css';
import { getSourceMeta } from '../data/mockData';
import { getAllActionItems, toggleActionItemStatus, deleteActionItem } from '../utils/actionItemsStore';

export default function ActionItemsView() {
  const [items, setItems] = useState([]);
  const [error, setError] = useState('');

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
            검색할 때마다 AI가 문서·대화에서 자동으로 뽑아낸 할 일을 한곳에서 관리하세요
          </p>
        </div>
      </div>

      <div className="dashboard__card glass-panel animate-fade-in-up delay-2">
        <div className="dashboard__card-header">
          <h2 className="dashboard__card-title">할 일 리스트</h2>
          <span className="dashboard__card-badge">{openCount}개 진행 중</span>
        </div>
        {items.length > 0 && (
          <div className="ai-panel__action-legend">
            동그라미를 클릭하면 상태가 바뀝니다 —
            <span className="ai-panel__action-legend-item"><span className="ai-panel__action-status ai-panel__action-status--pending ai-panel__action-status--mini">○</span> 대기</span>
            <span className="ai-panel__action-legend-item"><span className="ai-panel__action-status ai-panel__action-status--in-progress ai-panel__action-status--mini">◐</span> 진행 중</span>
            <span className="ai-panel__action-legend-item"><span className="ai-panel__action-status ai-panel__action-status--completed ai-panel__action-status--mini">✓</span> 완료</span>
          </div>
        )}
        {error && <p className="dashboard__empty" role="alert">⚠️ {error}</p>}
        <div className="ai-panel__action-list">
          {items.length === 0 && !error && (
            <p className="dashboard__empty">
              아직 할 일이 없습니다. 통합 검색을 실행하면 AI가 자동으로 추출해서 여기 쌓입니다.
            </p>
          )}
          {items.map((item) => {
            const source = getSourceMeta(item.source);
            return (
              <div key={item.id} className="ai-panel__action-item">
                <button
                  className={`ai-panel__action-status ai-panel__action-status--${item.status}`}
                  style={{ padding: 0, fontFamily: 'inherit', cursor: 'pointer' }}
                  onClick={() => handleToggle(item.id)}
                  title="클릭해서 상태 변경"
                >
                  {item.status === 'completed' ? '✓' : item.status === 'in-progress' ? '◐' : '○'}
                </button>
                <div className="ai-panel__action-content">
                  <div className="ai-panel__action-task">{item.task}</div>
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
