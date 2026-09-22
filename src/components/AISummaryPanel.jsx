import { useState, useEffect } from 'react';
import './AISummaryPanel.css';
import { getSourceMeta } from '../data/mockData';
import { saveActionItem } from '../utils/actionItemsStore';
import { summarizeDocument } from '../utils/apiClient';

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
  // 전체 요약과 문서별 요약이 둘 다 액션아이템 id를 "1","2"...로 새로 매기므로, 저장 여부는
  // 문서 id까지 합친 키로 구분해야 서로 안 섞인다.
  const [savedIds, setSavedIds] = useState(new Set());
  const [savingIds, setSavingIds] = useState(new Set());
  const [docSummary, setDocSummary] = useState(null);
  const [docSummaryError, setDocSummaryError] = useState('');
  const [docSummaryLoading, setDocSummaryLoading] = useState(false);

  // summary는 검색어가 똑같아도(같은 "최근 검색" 항목을 다시 클릭 등) 매번 새로 만들어진
  // 객체라, 검색어 문자열만 보면 "완전히 똑같은 검색을 다시 돌렸을 때" 이전 저장 상태가
  // 안 지워지는 문제가 있었다 — summary 자체를 의존성에 넣어 매 검색마다 확실히 초기화한다.
  useEffect(() => {
    setSavedIds(new Set());
  }, [searchQuery, summary]);

  // 문서를 클릭하면 그 문서 하나만 다시 요약한다 — 예전엔 검색 결과 전체(최대 4개)를 합친
  // 요약을 계속 보여줘서, 다른 문서를 클릭해도 무관한 문서 내용이 "핵심 포인트"에 섞여
  // 나오는 문제가 있었다(예: Slack 대화를 클릭했는데 Google Drive 문서 얘기가 나옴).
  useEffect(() => {
    if (!selectedDoc) {
      setDocSummary(null);
      setDocSummaryError('');
      return undefined;
    }
    let cancelled = false;
    setDocSummary(null);
    setDocSummaryError('');
    setDocSummaryLoading(true);
    summarizeDocument(searchQuery, selectedDoc)
      .then((s) => { if (!cancelled) setDocSummary(s); })
      .catch(() => { if (!cancelled) setDocSummaryError('이 문서 요약을 불러오지 못했습니다.'); })
      .finally(() => { if (!cancelled) setDocSummaryLoading(false); });
    return () => { cancelled = true; };
  }, [selectedDoc, searchQuery]);

  const keyFor = (item) => `${selectedDoc ? selectedDoc.id : 'agg'}-${item.id}`;

  const handleSaveActionItem = async (item) => {
    const key = keyFor(item);
    setSavingIds((prev) => new Set(prev).add(key));
    try {
      // item.id는 AI가 이번 요약에서만 유효하게 "1","2"...로 새로 매긴 임시 번호라, 검색
      // 전체 요약의 "1"과 문서별 요약의 "1"이 백엔드에서 같은 저장 키(user+query+id)로
      // 취급돼 서로 덮어쓰는 사고가 있었다 — 화면에 쓰는 것과 같은 스코프 키(key)를 그대로
      // 저장용 id로 보내서 저장 단계에서도 확실히 구분되게 한다.
      await saveActionItem(searchQuery, { ...item, id: key });
      setSavedIds((prev) => new Set(prev).add(key));
    } catch {
      // 실패해도 후보 목록 자체는 그대로 — 사용자가 다시 눌러볼 수 있게 버튼 상태만 원복
    } finally {
      setSavingIds((prev) => {
        const next = new Set(prev);
        next.delete(key);
        return next;
      });
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

  // 문서를 선택 중이면 그 문서 전용 요약을, 아니면 검색 결과 전체 요약을 보여준다.
  const activeSummary = selectedDoc ? docSummary : summary;

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
          AI 분석{selectedDoc && <span className="ai-panel__header-scope"> · 이 문서만</span>}
        </div>
        <h3 className="ai-panel__title">{activeSummary?.title || selectedDoc?.title || summary.title}</h3>
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
        {docSummaryLoading && (
          <div className="ai-panel__doc-summary-loading">
            <div className="ai-panel__doc-summary-spinner" />
            이 문서 요약 만드는 중…
          </div>
        )}
        {!docSummaryLoading && docSummaryError && (
          <p className="dashboard__empty" role="alert">⚠️ {docSummaryError}</p>
        )}
        {!docSummaryLoading && !docSummaryError && activeSummary && (
          <>
            {/* Summary Section */}
            {activeSection === 'summary' && (
              <div className="ai-panel__summary animate-fade-in">
                <div className="ai-panel__summary-header">
                  <span className="ai-panel__summary-icon">💡</span>
                  <span className="ai-panel__summary-label">핵심 포인트</span>
                </div>
                <ul className="ai-panel__key-points">
                  {activeSummary.keyPoints.map((point, i) => (
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
                  {activeSummary.decisionTrail.map((item, i) => {
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
                  <span className="ai-panel__summary-label">
                    {selectedDoc ? '이 문서에서 뽑아낸 할 일 후보' : '이 검색에서 뽑아낸 할 일 후보'}
                  </span>
                </div>
                <p className="ai-panel__actions-hint">
                  필요한 것만 골라 "추가" 눌러주세요 — 눌러야만 할 일 리스트에 저장됩니다.
                </p>
                <div className="ai-panel__action-list">
                  {activeSummary.actionItems.map((item, i) => {
                    const key = keyFor(item);
                    const isSaved = savedIds.has(key);
                    const isSaving = savingIds.has(key);
                    return (
                      <div key={key} className={`ai-panel__action-item delay-${i + 1} animate-fade-in-up`}>
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
                          disabled={isSaved || isSaving}
                        >
                          {isSaved ? '추가됨 ✓' : isSaving ? '추가 중…' : '+ 추가'}
                        </button>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
