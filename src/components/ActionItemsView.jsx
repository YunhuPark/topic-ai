import { useEffect, useState } from 'react';
import './Dashboard.css';
import './AISummaryPanel.css';
import { getSourceMeta } from '../data/mockData';
import { getAllActionItems, toggleActionItemStatus, deleteActionItem, saveActionItem } from '../utils/actionItemsStore';

// 검색 결과에서 고른 할 일은 백엔드가 "query + LLM이 매긴 임시 id" 조합으로 중복을 구분하는데,
// 수동 추가는 애초에 검색어가 없다 — 모든 수동 항목이 같은 고정 query("직접 추가")를 쓰는 대신
// source_item_id(=이 id)만 매번 새로 발급해서, 같은 (query, source_item_id) 쌍으로 다른
// 수동 항목을 덮어쓰는 사고를 방지한다.
const MANUAL_QUERY = '직접 추가';
function generateManualId() {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) return `manual-${crypto.randomUUID()}`;
  return `manual-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

export default function ActionItemsView({ teamId } = {}) {
  const [items, setItems] = useState([]);
  const [error, setError] = useState('');
  // 기본을 '전체'로 둔다 — '진행 중'을 기본으로 뒀더니, 체크하는 순간 그 항목이 목록에서
  // 바로 사라져서(완료 탭으로 넘어가서) 사용자가 "체크가 됐는지 안 됐는지" 헷갈려했다.
  // '전체'가 기본이면 체크한 항목이 같은 화면에 취소선 처리로 남아서 바로 눈에 보인다.
  const [filter, setFilter] = useState('all'); // 'all' | 'open' | 'completed'
  const [showAddForm, setShowAddForm] = useState(false);
  const [newTask, setNewTask] = useState('');
  const [newAssignee, setNewAssignee] = useState('');
  const [newDueDate, setNewDueDate] = useState('');
  const [adding, setAdding] = useState(false);

  useEffect(() => {
    getAllActionItems(teamId)
      .then(setItems)
      .catch((e) => setError(e.message));
  }, [teamId]);

  // 실패해도 목록을 비우지 않는다 — 예전엔 오류 시 빈 배열을 넣어서, 한 번의 네트워크 오류로
  // 할 일이 전부 사라진 것처럼 보였다.
  const handleToggle = (id) => {
    setError('');
    toggleActionItemStatus(id, teamId).then(setItems).catch((e) => setError(e.message));
  };

  const handleDelete = (id) => {
    setError('');
    deleteActionItem(id, teamId).then(setItems).catch((e) => setError(e.message));
  };

  const handleAddManual = (e) => {
    e.preventDefault();
    const task = newTask.trim();
    if (!task) return;
    setError('');
    setAdding(true);
    const item = {
      id: generateManualId(),
      task,
      assignee: newAssignee.trim() || '미정',
      dueDate: newDueDate,
      status: 'pending',
      source: 'manual',
    };
    saveActionItem(MANUAL_QUERY, item, teamId)
      .then((rows) => {
        setItems(rows);
        setNewTask('');
        setNewAssignee('');
        setNewDueDate('');
        setShowAddForm(false);
      })
      .catch((e) => setError(e.message))
      .finally(() => setAdding(false));
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
          <div className="action-items__header-actions">
            <button
              type="button"
              className="action-items__add-toggle"
              onClick={() => setShowAddForm((v) => !v)}
            >
              {showAddForm ? '취소' : '+ 새 할 일 추가'}
            </button>
            <span className="dashboard__card-badge">{openCount}개 진행 중</span>
          </div>
        </div>
        {showAddForm && (
          <form className="action-items__add-form" onSubmit={handleAddManual}>
            <input
              className="action-items__add-input"
              type="text"
              placeholder="할 일 (예: 발표 자료 검토받기)"
              value={newTask}
              onChange={(e) => setNewTask(e.target.value)}
              autoFocus
              required
            />
            <div className="action-items__add-row">
              <input
                className="action-items__add-input"
                type="text"
                placeholder="담당자 (선택, 기본값: 미정)"
                value={newAssignee}
                onChange={(e) => setNewAssignee(e.target.value)}
              />
              <input
                className="action-items__add-input"
                type="date"
                value={newDueDate}
                onChange={(e) => setNewDueDate(e.target.value)}
              />
            </div>
            <button type="submit" className="people-manager__button" disabled={adding}>
              {adding ? '추가 중...' : '추가'}
            </button>
          </form>
        )}
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
              아직 할 일이 없습니다. 검색 결과의 "할 일 리스트" 탭에서 "+ 추가"를 누르거나,
              위의 "+ 새 할 일 추가"로 직접 적어서 쌓아보세요.
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
                    {item.dueDate && <span>📅 {item.dueDate}</span>}
                    {item.source === 'manual' ? (
                      <span>✍️ 직접 추가</span>
                    ) : (
                      <span>🔍 "{item.query}"</span>
                    )}
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
