from pydantic import BaseModel
from typing import List, Optional

class Document(BaseModel):
    id: str
    title: str
    source: str
    author: str
    authorAvatar: str
    date: str
    snippet: str
    content: str
    tags: List[str]
    freshness: str
    relevance: float
    sourceUrl: Optional[str] = ""

class ActionItem(BaseModel):
    id: str
    task: str
    assignee: str
    dueDate: str
    status: str
    source: str

class DecisionTrailItem(BaseModel):
    date: str
    decision: str
    source: str

class Summary(BaseModel):
    title: str
    keyPoints: List[str]
    decisionTrail: List[DecisionTrailItem]
    actionItems: List[ActionItem]

class SearchTiming(BaseModel):
    """검색 요청 한 번의 단계별 소요 시간(ms) — 실측 응답 속도를 보여주기 위한 계측치.
    벡터 검색/재정렬, 소스별 실시간 권한 확인, LLM 요약 호출 세 단계가 전체 지연의 대부분을
    차지해서, 이 셋을 각각 나눠 봐야 어디가 병목인지 알 수 있다."""
    retrievalMs: int
    permissionCheckMs: int
    llmSummaryMs: int
    totalMs: int

class SearchResponse(BaseModel):
    documents: List[Document]
    summary: Summary
    # 권한 확인이 "권한 없음"이 아니라 "토큰 만료/일시적 실패"로 끝난 소스들 — 문서가 조용히
    # 사라지는 대신 프론트가 재연결 안내를 띄울 수 있게 함께 내려준다.
    disconnectedSources: List[str] = []
    degradedSources: List[str] = []
    timing: Optional[SearchTiming] = None

class SummarizeDocumentRequest(BaseModel):
    # 검색 결과에서 문서 하나를 클릭했을 때 그 문서만 다시 요약하기 위한 요청 — 예전엔
    # 검색 결과 전체(최대 4개)를 합친 요약을 계속 보여줘서, 다른 문서를 클릭해도 무관한
    # 내용이 "핵심 포인트"에 섞여 나왔다. document는 id를 찾는 용도일 뿐 — 서버가 실제
    # 문서를 다시 조회하고 권한도 재확인한다(클라이언트가 보낸 content는 신뢰하지 않음).
    query: str
    document: Document
    team_id: Optional[int] = None

class SourceCount(BaseModel):
    source: str
    count: int

class FreshnessBreakdown(BaseModel):
    fresh: int
    moderate: int
    stale: int

class TopicItem(BaseModel):
    id: str
    label: str
    source: str
    date: str

class StatsResponse(BaseModel):
    totalDocuments: int
    connectedSources: int
    sources: List[SourceCount]
    freshness: FreshnessBreakdown
    topics: List[TopicItem]

class SignupRequest(BaseModel):
    email: str
    password: str

class LoginRequest(BaseModel):
    email: str
    password: str

class AuthResponse(BaseModel):
    token: str
    email: str

class MeResponse(BaseModel):
    id: int
    email: str

class LinkedAccount(BaseModel):
    provider: str
    provider_email: str
    linked_at: str

class SearchHistoryItem(BaseModel):
    query: str
    searched_at: str

class SearchCountResponse(BaseModel):
    count: int

class AuthorizeUrlResponse(BaseModel):
    authorizeUrl: str

class SyncStatusItem(BaseModel):
    provider: str
    status: str  # "running" | "done" | "error"
    startedAt: Optional[str] = None
    finishedAt: Optional[str] = None
    lastCount: Optional[int] = None
    error: Optional[str] = None
    phase: Optional[str] = None  # "fetching"(원본에서 목록 수집) | "embedding"(임베딩 중)
    done: Optional[int] = None
    total: Optional[int] = None

class SyncStatusResponse(BaseModel):
    items: List[SyncStatusItem]

class ActionItemRecord(BaseModel):
    id: int
    query: str
    task: str
    assignee: str
    due_date: str
    status: str
    source: str
    saved_at: str

class SaveActionItemRequest(BaseModel):
    # 검색 결과(summary.actionItems)에서 사용자가 직접 고른 항목 하나를 저장할 때 쓴다 —
    # 어느 검색에서 나온 항목인지도 같이 필요하다(action_items 테이블의 유니크 키가
    # user_id+query+source_item_id 조합이라서).
    query: str
    item: ActionItem
    team_id: Optional[int] = None

class PersonRecord(BaseModel):
    id: int
    display_name: str
    aliases: list[str]
    created_at: str

class PersonCreateRequest(BaseModel):
    display_name: str
    aliases: list[str]
    team_id: Optional[int] = None

class TeamRecord(BaseModel):
    id: int
    name: str
    role: str
    createdAt: str

class TeamCreateRequest(BaseModel):
    name: str

class TeamInviteResponse(BaseModel):
    code: str

class TeamJoinRequest(BaseModel):
    code: str

class TeamMemberRecord(BaseModel):
    userId: int
    email: str
    role: str
    joinedAt: str
