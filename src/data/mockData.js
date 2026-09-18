// UI 설정 매핑 (소스/신선도별 라벨·아이콘·색상). 실제 콘텐츠 데이터는 전부 백엔드 API에서 가져온다.
export const sourceConfig = {
  notion: { label: 'Notion', icon: '📓', color: 'var(--notion-color)', bg: 'var(--notion-bg)' },
  slack: { label: 'Slack', icon: '💬', color: 'var(--slack-color)', bg: 'var(--slack-bg)' },
  gdrive: { label: 'Google Drive', icon: '📁', color: 'var(--gdrive-color)', bg: 'var(--gdrive-bg)' },
  github: { label: 'GitHub', icon: '🐙', color: 'var(--github-color)', bg: 'var(--github-bg)' },
  gitlab: { label: 'GitLab', icon: '🦊', color: 'var(--gitlab-color)', bg: 'var(--gitlab-bg)' },
  jira: { label: 'Jira', icon: '🔷', color: 'var(--jira-color)', bg: 'var(--jira-bg)' },
};

// LLM이 source에 우리가 아는 커넥터 키(notion/slack/...) 대신 문서 제목 같은 다른 문자열을
// 돌려줄 때도 있어서, 모르는 값이면 깨지지 않고 무난한 기본 배지로 대체한다.
export function getSourceMeta(sourceKey) {
  return sourceConfig[sourceKey] ?? {
    icon: '📄',
    label: sourceKey || '출처 미상',
    bg: 'var(--bg-tertiary)',
    color: 'var(--text-tertiary)',
  };
}

export const freshnessConfig = {
  fresh: { label: '최신', color: 'var(--success)', bg: 'var(--success-bg)', icon: '🟢' },
  moderate: { label: '보통', color: 'var(--warning)', bg: 'var(--warning-bg)', icon: '🟡' },
  stale: { label: '오래됨', color: 'var(--danger)', bg: 'var(--danger-bg)', icon: '🔴' },
};
