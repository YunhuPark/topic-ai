import { useState, useEffect } from 'react';
import './PeopleManager.css';
import { getAllPeople, createPerson, deletePerson } from '../utils/peopleStore';

// "승현" 한 마디만 나와도 AI가 정식 이름을 알아서 붙일 수 있도록, 사용자가 직접 관리하는
// 별칭 사전. OAuth가 필요 없는 순수 텍스트 등록이라 PopupLinkPanel과 달리 훨씬 단순하다.
export default function PeopleManager({ onCountChange, teamId }) {
  const [people, setPeople] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [name, setName] = useState('');
  const [aliasInput, setAliasInput] = useState('');
  const [saving, setSaving] = useState(false);
  const [deletingId, setDeletingId] = useState(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    getAllPeople(teamId)
      .then((rows) => { if (!cancelled) setPeople(rows); })
      .catch((err) => { if (!cancelled) setError(err.message); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [teamId]);

  useEffect(() => { onCountChange?.(people.length); }, [people, onCountChange]);

  const handleAdd = async (e) => {
    e.preventDefault();
    const displayName = name.trim();
    const aliases = aliasInput.split(',').map((a) => a.trim()).filter(Boolean);
    if (!displayName || aliases.length === 0) {
      setError('이름과 별칭을 하나 이상 입력해주세요.');
      return;
    }
    setError('');
    setSaving(true);
    try {
      const rows = await createPerson(displayName, aliases, teamId);
      setPeople(rows);
      setName('');
      setAliasInput('');
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (id) => {
    setError('');
    setDeletingId(id);
    try {
      const rows = await deletePerson(id, teamId);
      setPeople(rows);
    } catch (err) {
      setError(err.message);
    } finally {
      setDeletingId(null);
    }
  };

  return (
    <div className="people-manager">
      <p className="people-manager__hint">
        "승현"처럼 이름만 나와도 AI가 헷갈리지 않도록, 정식 이름과 자주 쓰이는 별칭을 등록해두세요.
        {teamId ? ' 지금 선택된 팀 전체가 공유하는 사전입니다.' : ' 지금은 개인 사전입니다.'}
      </p>

      {loading ? (
        <p className="people-manager__hint">불러오는 중...</p>
      ) : (
        <div className="people-manager__list">
          {people.map((p) => (
            <div key={p.id} className="people-manager__item">
              <div className="people-manager__item-info">
                <span className="people-manager__item-name">{p.displayName}</span>
                <div className="people-manager__item-aliases">
                  {p.aliases.map((a) => (
                    <span key={a} className="people-manager__alias-chip">{a}</span>
                  ))}
                </div>
              </div>
              <button
                className="people-manager__delete"
                onClick={() => handleDelete(p.id)}
                disabled={deletingId === p.id}
                title="삭제"
              >
                {deletingId === p.id ? '...' : '×'}
              </button>
            </div>
          ))}
          {people.length === 0 && (
            <p className="people-manager__hint">아직 등록된 팀원이 없어요.</p>
          )}
        </div>
      )}

      <form className="people-manager__form" onSubmit={handleAdd}>
        <input
          className="people-manager__input"
          type="text"
          placeholder="이름 (예: 송승현)"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <input
          className="people-manager__input"
          type="text"
          placeholder="별칭 (콤마로 구분, 예: 승현, 승현님)"
          value={aliasInput}
          onChange={(e) => setAliasInput(e.target.value)}
        />
        <button className="people-manager__button" type="submit" disabled={saving}>
          {saving ? '추가 중...' : '+ 팀원 추가'}
        </button>
      </form>

      {error && <p className="people-manager__error">{error}</p>}
    </div>
  );
}
