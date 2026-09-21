import { useState } from 'react';
import './TopicThread.css';
import { sourceConfig, freshnessConfig } from '../data/mockData';

function DocumentCard({ doc, isSelected, onSelect }) {
  const source = sourceConfig[doc.source];
  const freshness = freshnessConfig[doc.freshness];

  return (
    <div
      className={`doc-card glass-panel-hover ${isSelected ? 'doc-card--selected' : ''}`}
      onClick={() => onSelect(doc)}
    >
      <div className="doc-card__header">
        <span className="doc-card__source" style={{ background: source.bg, color: source.color }}>
          {source.icon} {source.label}
        </span>
        <span className="doc-card__freshness" style={{ background: freshness.bg, color: freshness.color }}>
          {freshness.icon} {freshness.label}
        </span>
      </div>
      <h3 className="doc-card__title">{doc.title}</h3>
      <p className="doc-card__snippet">{doc.snippet}</p>
      <div className="doc-card__footer">
        <div className="doc-card__author">
          <span className="doc-card__avatar" style={{ background: source.color }}>
            {doc.authorAvatar}
          </span>
          <span className="doc-card__author-name">{doc.author}</span>
        </div>
        <span className="doc-card__date">{doc.date}</span>
      </div>
      <div className="doc-card__tags">
        {doc.tags.map((tag, i) => (
          <span key={i} className="doc-card__tag">#{tag}</span>
        ))}
      </div>
      <div className="doc-card__relevance-bar">
        <div
          className="doc-card__relevance-fill"
          style={{ width: `${doc.relevance * 100}%` }}
        />
      </div>
    </div>
  );
}

const FRESHNESS_RANK = { fresh: 0, moderate: 1, stale: 2 };

export default function TopicThread({ documents, onDocSelect, selectedDoc }) {
  const [activeTab, setActiveTab] = useState('all');
  const [sortBy, setSortBy] = useState('relevance');

  // 실제 검색 결과에 등장한 소스만큼만 탭을 만든다 — 새 커넥터가 추가돼도 따로 고칠 필요 없음
  const presentSources = [...new Set(documents.map((d) => d.source))];
  const tabs = [
    { id: 'all', label: '전체', count: documents.length },
    ...presentSources.map((src) => ({
      id: src,
      label: `${sourceConfig[src]?.icon ?? ''} ${sourceConfig[src]?.label ?? src}`,
      count: documents.filter((d) => d.source === src).length,
    })),
  ];

  const filteredDocs = activeTab === 'all'
    ? documents
    : documents.filter(d => d.source === activeTab);

  const sortedDocs = [...filteredDocs].sort((a, b) => {
    if (sortBy === 'date') return b.date.localeCompare(a.date);
    if (sortBy === 'freshness') return FRESHNESS_RANK[a.freshness] - FRESHNESS_RANK[b.freshness];
    return b.relevance - a.relevance;
  });

  return (
    <div className="topic-thread">
      {/* Header with result count */}
      <div className="topic-thread__header">
        <div className="topic-thread__result-info">
          <h2 className="topic-thread__title">
            <span className="topic-thread__title-icon">🧵</span>
            Topic Thread
          </h2>
          <span className="topic-thread__count">
            {documents.length}개 문서 발견
          </span>
        </div>
        <div className="topic-thread__sort">
          <select
            className="topic-thread__sort-select"
            id="sort-select"
            value={sortBy}
            onChange={(e) => setSortBy(e.target.value)}
          >
            <option value="relevance">관련도순</option>
            <option value="date">최신순</option>
            <option value="freshness">신선도순</option>
          </select>
        </div>
      </div>

      {/* Source Tabs */}
      <div className="topic-thread__tabs">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            className={`topic-thread__tab ${activeTab === tab.id ? 'topic-thread__tab--active' : ''}`}
            onClick={() => setActiveTab(tab.id)}
          >
            {tab.label}
            <span className="topic-thread__tab-count">{tab.count}</span>
          </button>
        ))}
      </div>

      {/* Document List */}
      <div className="topic-thread__list">
        {sortedDocs.length === 0 && (
          // 권한 필터로 결과가 0건인 경우 — 예전엔 "0개 문서 발견"과 빈 목록만 남아서
          // 왜 아무것도 없는지 알 수 없었다. 이유는 오른쪽 요약 패널에 들어있다.
          <p className="topic-thread__empty">
            표시할 수 있는 문서가 없습니다. 오른쪽 요약에서 이유를 확인해 주세요.
          </p>
        )}
        {sortedDocs.map((doc, index) => (
          <div key={doc.id} className={`animate-fade-in-up delay-${index + 1}`}>
            <DocumentCard
              doc={doc}
              isSelected={selectedDoc?.id === doc.id}
              onSelect={onDocSelect}
            />
          </div>
        ))}
      </div>
    </div>
  );
}
