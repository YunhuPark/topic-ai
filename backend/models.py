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

class SearchResponse(BaseModel):
    documents: List[Document]
    summary: Summary
    # 권한 확인이 "권한 없음"이 아니라 "토큰 만료/일시적 실패"로 끝난 소스들 — 문서가 조용히
    # 사라지는 대신 프론트가 재연결 안내를 띄울 수 있게 함께 내려준다.
    disconnectedSources: List[str] = []
    degradedSources: List[str] = []

class SummarizeDocumentRequest(BaseModel):
    # 검색 결과에서 문서 하나를 클릭했을 때 그 문서만 다시 요약하기 위한 요청 — 예전엔
    # 검색 결과 전체(최대 4개)를 합친 요약을 계속 보여줘서, 다른 문서를 클릭해도 무관한
    # 내용이 "핵심 포인트"에 섞여 나왔다. 이미 검색 응답으로 받은 문서라 권한은 다시
    # 확인하지 않는다(그 사람이 이미 본 결과이므로).
    query: str
    document: Document

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
