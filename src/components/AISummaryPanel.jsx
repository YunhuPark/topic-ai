import { useState, useEffect } from 'react';
import './AISummaryPanel.css';
import { getSourceMeta } from '../data/mockData';
import { saveActionItem } from '../utils/actionItemsStore';

function TypingEffect({ text, speed = 15 }) {
  const [displayed, setDisplayed] = useState('');
  const [done, setDone] = useState(false);

  useEffect(() => {
    setDisplayed('');
    setDone(false);
    let i = 0;
    const interval = setInterval(() => {
      if (i < text.length) {
        setDisplayed(text.slice(0, i + 1));
        i++;
      } else {
        setDone(true);
        clearInterval(interval);
      }
    }, speed);
    return () => clearInterval(interval);
  }, [text, speed]);

  return (
    <span>
      {displayed}
      {!done && <span className="typing-cursor">|</span>}
    </span>
  );
}

export default function AISummaryPanel({ summary, selectedDoc, searchQuery }) {
  const [activeSection, setActiveSection] = useState('summary');
  // 검색 결과의 할 일 후보 중 이번 화면에서 이미 저장 누른 것 — 검색어가 바뀌면(새 검색) 초기화.
  const [savedIds, setSavedIds] = useState(new Set());
  const [savingId, setSavingId] = useState(null);

  useEffect(() => {
    setSavedIds(new Set());
  }, [searchQuery]);

  const handleSaveActionItem = async (item) => {
    setSavingId(item.id);
    try {
      await saveActionItem(searchQuery, item);
      setSavedIds((prev) => new Set(prev).add(item.id));
    } catch {
      // 실패해도 후보 목록 자체는 그대로 — 사용자가 다시 눌러볼 수 있게 버튼 상태만 원복
    } finally {
      setSavingId(null);
    }
  };

  if (!summary) {
    return (
      <div className="ai-panel">
        <div className="ai-panel__empty">
          <div className="ai-panel__empty-icon">🤖</div>
          <p className="ai-panel__empty-text">검색을 실행하면<br/>AI가 분석 결과를 보여드립니다</p>
        </div>
      </div>
    );
  }

  const sections = [
    { id: 'summary', label: '📝 AI 요약', icon: '📝' },
    { id: 'decisions', label: '🔗 의사결정 흐름', icon: '🔗' },
    { id: 'actions', label: '⚡ 할 일 리스트', icon: '⚡' },
  ];

  return (
    <div className="ai-panel animate-slide-right">
      {/* Header */}
      <div className="ai-panel__header">
        <div className="ai-panel__header-badge">
          <span className="ai-panel__header-dot" />
          AI 분석
        </div>
        <h3 className="ai-panel__title">{summary.title}</h3>
      </div>

      {/* Section Tabs */}
      <div className="ai-panel__section-tabs">
        {sections.map((section) => (
          <button
            key={section.id}
            className={`ai-panel__section-tab ${activeSection === section.id ? 'ai-panel__section-tab--active' : ''}`}
            onClick={() => setActiveSection(section.id)}
          >
            {section.label}
          </button>
        ))}
      </div>

      {/* Content */}
      <div className="ai-panel__content">
        {/* Summary Section */}
        {activeSection === 'summary' && (
          <div className="ai-panel__summary animate-fade-in">
            <div className="ai-panel__summary-header">
              <span className="ai-panel__summary-icon">💡</span>
              <span className="ai-panel__summary-label">핵심 포인트</span>
            </div>
            <ul className="ai-panel__key-points">
              {summary.keyPoints.map((point, i) => (
                <li key={i} className={`ai-panel__key-point delay-${i + 1} animate-fade-in-up`}>
                  <span className="ai-panel__key-point-number">{i + 1}</span>
                  <span className="ai-panel__key-point-text">{point}</span>
                </li>
              ))}
            </ul>

            {/* Document Preview */}
            {selectedDoc && (
              <div className="ai-panel__preview">
                <div className="ai-panel__preview-header">
                  <span>📄 문서 미리보기</span>
                  {selectedDoc.sourceUrl && (
                    <a
                      href={selectedDoc.sourceUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="ai-panel__preview-link"
                    >
                      원문 보기 ↗
                    </a>
                  )}
                </div>
                <div className="ai-panel__preview-content">
                  <pre>{selectedDoc.content}</pre>
                </div>
              </div>
            )}
          </div>
        )}

        {/* Decision Trail Section */}
        {activeSection === 'decisions' && (
          <div className="ai-panel__decisions animate-fade-in">
            <div className="ai-panel__summary-header">
              <span className="ai-panel__summary-icon">🔗</span>
              <span className="ai-panel__summary-label">의사결정 흐름</span>
            </div>
            <div className="ai-panel__timeline">
              {summary.decisionTrail.map((item, i) => {
                const source = getSourceMeta(item.source);
                return (
                  <div key={i} className={`ai-panel__timeline-item delay-${i + 1} animate-fade-in-up`}>
                    <div className="ai-panel__timeline-dot" />
                    <div className="ai-panel__timeline-content">
                      <div className="ai-panel__timeline-date">{item.date}</div>
                      <div className="ai-panel__timeline-decision">{item.decision}</div>
                      <span className="ai-panel__timeline-source" style={{ background: source.bg, color: source.color }}>
                        {source.icon} {source.label}
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Action Items Section */}
        {activeSection === 'actions' && (
          <div className="ai-panel__actions animate-fade-in">
            <div className="ai-panel__summary-header">
              <span className="ai-panel__summary-icon">⚡</span>
              <span className="ai-panel__summary-label">이 검색에서 뽑아낸 할 일 후보</span>
            </div>
            <p className="ai-panel__actions-hint">
              필요한 것만 골라 "추가" 눌러주세요 — 눌러야만 할 일 리스트에 저장됩니다.
            </p>
            <div className="ai-panel__action-list">
              {summary.actionItems.map((item, i) => {
                const isSaved = savedIds.has(item.id);
                return (
                  <div key={item.id} className={`ai-panel__action-item delay-${i + 1} animate-fade-in-up`}>
                    <div className={`ai-panel__action-status ai-panel__action-status--${item.status}`}>
                      {item.status === 'completed' ? '✓' : item.status === 'in-progress' ? '◐' : '○'}
                    </div>
                    <div className="ai-panel__action-content">
                      <div className="ai-panel__action-task">{item.task}</div>
                      <div className="ai-panel__action-meta">
                        <span className="ai-panel__action-assignee">👤 {item.assignee}</span>
                        <span className="ai-panel__action-due">📅 {item.dueDate}</span>
                      </div>
                    </div>
                    <span
                      className="ai-panel__action-source-badge"
                      style={{
                        background: getSourceMeta(item.source).bg,
                        color: getSourceMeta(item.source).color,
                      }}
                    >
                      {getSourceMeta(item.source).icon}
                    </span>
                    <button
                      type="button"
                      className={`ai-panel__action-save ${isSaved ? 'ai-panel__action-save--done' : ''}`}
                      onClick={() => handleSaveActionItem(item)}
                      disabled={isSaved || savingId === item.id}
                    >
                      {isSaved ? '추가됨 ✓' : savingId === item.id ? '추가 중…' : '+ 추가'}
                    </button>
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
