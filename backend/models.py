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

class LinkGoogleRequest(BaseModel):
    accessToken: str

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

class SyncResponse(BaseModel):
    provider: str
    count: int

class ActionItemRecord(BaseModel):
    id: int
    query: str
    task: str
    assignee: str
    due_date: str
    status: str
    source: str
    saved_at: str
