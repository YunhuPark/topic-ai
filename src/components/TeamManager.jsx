import { useState, useEffect } from 'react';
import './PeopleManager.css';
import './TeamManager.css';
import {
  getAllTeams, createTeam, createInvite, joinTeam, getTeamMembers, removeTeamMember,
} from '../utils/teamStore';

// "팀원 관리"(별칭 사전, PeopleManager.jsx)와 이름이 겹치지 않게 "내 팀"으로 부른다 — 이건
// 진짜 팀(조직) 개념으로, 할 일 리스트·별칭 사전·통계를 여러 명이 같이 쓸 수 있게 해준다.
// 이메일 발송(SMTP)이 없어서 Discord/Slack처럼 초대 코드 방식으로 참여한다.
//
// 새 팀 만들기/참여하기 폼을 항상 펼쳐두면 사이드바가 너무 복잡해진다는 피드백을 받아서,
// 평소엔 접어두고 텍스트 링크를 눌렀을 때만 그 폼 하나만 펼치는 구조로 바꿨다(둘 다 동시에
// 펼쳐지지 않음 — 'create' | 'join' | null).
export default function TeamManager({ currentTeamId, onTeamChange, currentUserId }) {
  const [teams, setTeams] = useState([]);
  const [error, setError] = useState('');
  const [openForm, setOpenForm] = useState(null); // 'create' | 'join' | null
  const [newTeamName, setNewTeamName] = useState('');
  const [creating, setCreating] = useState(false);
  const [joinCode, setJoinCode] = useState('');
  const [joining, setJoining] = useState(false);
  const [members, setMembers] = useState([]);
  const [membersLoading, setMembersLoading] = useState(false);
  const [inviteCode, setInviteCode] = useState('');
  const [invitingLoading, setInvitingLoading] = useState(false);
  const [copyDone, setCopyDone] = useState(false);
  const [removingUserId, setRemovingUserId] = useState(null);

  const refreshTeams = () => (
    getAllTeams()
      .then((rows) => { setTeams(rows); return rows; })
      .catch((err) => { setError(err.message); return null; })
  );

  useEffect(() => { refreshTeams(); }, []);

  const currentTeam = teams.find((t) => t.id === currentTeamId) || null;

  useEffect(() => {
    setInviteCode('');
    setCopyDone(false);
    if (!currentTeamId) {
      setMembers([]);
      return undefined;
    }
    let cancelled = false;
    setMembersLoading(true);
    getTeamMembers(currentTeamId)
      .then((rows) => { if (!cancelled) setMembers(rows); })
      .catch((err) => { if (!cancelled) setError(err.message); })
      .finally(() => { if (!cancelled) setMembersLoading(false); });
    return () => { cancelled = true; };
  }, [currentTeamId]);

  const handleCreateTeam = async (e) => {
    e.preventDefault();
    const name = newTeamName.trim();
    if (!name) return;
    setError('');
    setCreating(true);
    try {
      // createTeam이 만들어진 팀을 직접 돌려주므로 그걸 그대로 쓴다 — 이름으로 다시 찾으면
      // 같은 이름의 팀이 이미 있을 때 엉뚱한(기존) 팀으로 전환될 수 있다.
      const created = await createTeam(name);
      await refreshTeams();
      onTeamChange(created.id);
      setNewTeamName('');
      setOpenForm(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setCreating(false);
    }
  };

  const handleJoin = async (e) => {
    e.preventDefault();
    const code = joinCode.trim();
    if (!code) return;
    setError('');
    setJoining(true);
    try {
      const joined = await joinTeam(code);
      await refreshTeams();
      onTeamChange(joined.id);
      setJoinCode('');
      setOpenForm(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setJoining(false);
    }
  };

  const handleCreateInvite = async () => {
    setError('');
    setInvitingLoading(true);
    try {
      const { code } = await createInvite(currentTeamId);
      setInviteCode(code);
      setCopyDone(false);
    } catch (err) {
      setError(err.message);
    } finally {
      setInvitingLoading(false);
    }
  };

  const handleCopyInvite = async () => {
    try {
      await navigator.clipboard.writeText(inviteCode);
      setCopyDone(true);
    } catch {
      // 클립보드 접근 실패 시 조용히 무시 — 코드는 화면에 이미 보인다
    }
  };

  const handleRemoveMember = async (userId) => {
    setError('');
    setRemovingUserId(userId);
    try {
      const rows = await removeTeamMember(currentTeamId, userId);
      if (userId === currentUserId) {
        // 내가 나간 경우 — "현재 팀" 선택이 그대로 남아있으면 더 이상 멤버가 아닌 팀으로
        // 계속 요청을 보내서 이후 전부 403이 난다. 개인 스코프로 되돌린다.
        onTeamChange(null);
      } else {
        setMembers(rows);
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setRemovingUserId(null);
    }
  };

  // "나가기"는 반드시 본인(currentUserId)만 지워야 한다 — 목록에서 아무 멤버나 골라 지우면
  // 엉뚱한 사람이 쫓겨난다.
  const handleLeave = () => handleRemoveMember(currentUserId);

  const toggleForm = (form) => {
    setError('');
    setOpenForm((prev) => (prev === form ? null : form));
  };

  return (
    <div className="people-manager team-manager">
      <div className="team-manager__switcher">
        <select
          className="people-manager__input"
          value={currentTeamId ?? ''}
          onChange={(e) => onTeamChange(e.target.value ? Number(e.target.value) : null)}
        >
          <option value="">개인</option>
          {teams.map((t) => (
            <option key={t.id} value={t.id}>{t.name} · {t.role === 'owner' ? '소유자' : '멤버'}</option>
          ))}
        </select>
      </div>

      {currentTeam ? (
        <>
          {membersLoading && (
            <p className="people-manager__hint">멤버 목록 불러오는 중…</p>
          )}
          {!membersLoading && (
            <div className="people-manager__list">
              {members.map((m) => (
                <div key={m.userId} className="team-manager__member-row">
                  <span className="team-manager__member-email">{m.email}</span>
                  <span className="team-manager__member-role">{m.role === 'owner' ? '소유자' : '멤버'}</span>
                  {currentTeam.role === 'owner' && m.role !== 'owner' && (
                    <button
                      className="team-manager__copy-button team-manager__copy-button--danger"
                      onClick={() => handleRemoveMember(m.userId)}
                      disabled={removingUserId === m.userId}
                      title="내보내기"
                    >
                      {removingUserId === m.userId ? '...' : '내보내기'}
                    </button>
                  )}
                </div>
              ))}
            </div>
          )}

          {currentTeam.role === 'owner' ? (
            <div className="team-manager__invite">
              {inviteCode ? (
                <div className="team-manager__invite-code">
                  <code>{inviteCode}</code>
                  <button type="button" className="team-manager__copy-button" onClick={handleCopyInvite}>
                    {copyDone ? '복사됨 ✓' : '복사'}
                  </button>
                </div>
              ) : (
                <button
                  type="button"
                  className="people-manager__button"
                  onClick={handleCreateInvite}
                  disabled={invitingLoading}
                >
                  {invitingLoading ? '만드는 중...' : '초대 코드 만들기'}
                </button>
              )}
            </div>
          ) : (
            <button type="button" className="team-manager__text-link team-manager__text-link--danger" onClick={handleLeave}>
              이 팀 나가기
            </button>
          )}
        </>
      ) : (
        <p className="people-manager__hint">
          팀을 만들거나 초대 코드로 참여하면, 할 일 리스트·별칭 사전·통계를 팀 전체가 같이 씁니다.
        </p>
      )}

      <div className="team-manager__toggles">
        <button type="button" className="team-manager__text-link" onClick={() => toggleForm('create')}>
          + 새 팀 만들기
        </button>
        <button type="button" className="team-manager__text-link" onClick={() => toggleForm('join')}>
          초대 코드로 참여
        </button>
      </div>

      {openForm === 'create' && (
        <form className="people-manager__form" onSubmit={handleCreateTeam}>
          <input
            className="people-manager__input"
            type="text"
            placeholder="새 팀 이름"
            autoFocus
            value={newTeamName}
            onChange={(e) => setNewTeamName(e.target.value)}
          />
          <button className="people-manager__button" type="submit" disabled={creating}>
            {creating ? '만드는 중...' : '만들기'}
          </button>
        </form>
      )}

      {openForm === 'join' && (
        <form className="people-manager__form" onSubmit={handleJoin}>
          <input
            className="people-manager__input"
            type="text"
            placeholder="초대 코드 붙여넣기"
            autoFocus
            value={joinCode}
            onChange={(e) => setJoinCode(e.target.value)}
          />
          <button className="people-manager__button" type="submit" disabled={joining}>
            {joining ? '참여 중...' : '참여하기'}
          </button>
        </form>
      )}

      {error && <p className="people-manager__error">{error}</p>}
    </div>
  );
}
