import hashlib
import json
import os
import re
import sys
import threading
import time
from datetime import datetime, timezone
from typing import List, Optional
from dotenv import load_dotenv

# Set ENV vars before importing to optimize load if needed
os.environ["TOKENIZERS_PARALLELISM"] = "false"
load_dotenv()

# Windows 콘솔(cp949)에서 이모지 print가 UnicodeEncodeError를 던지는 것 방지
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_community.vectorstores import Chroma
from openai import OpenAI, RateLimitError

from dummy_data import mock_documents
from models import Summary
import llm_backend
import db

# 1. 임베딩 모델 설정
#
# langchain_openai(OpenAIEmbeddings/ChatOpenAI) 대신 openai SDK를 직접 쓴다 —
# langchain_openai는 import만 해도 tiktoken(서명 없는 네이티브 모듈)을 불러오는데, Windows의
# Smart App Control이 그걸 차단하면 백엔드 자체가 기동하지 못한다. 모델과 호출 파라미터가 같아서
# 만들어지는 벡터는 동일하므로, 이미 적재된 문서를 다시 임베딩할 필요는 없다.
EMBEDDING_MODEL = "text-embedding-3-small"
# gpt-4o 대비 비용이 훨씬 저렴하면서(약 1/15) 이 구조화된 JSON 요약 작업에는 품질 차이가
# 크게 체감되지 않는다 — 회사 규모로 사용량이 늘어도 비용이 감당 가능한 수준으로 유지된다.
SUMMARY_MODEL = "gpt-4o-mini"
OPENAI_TIMEOUT_SECONDS = 60

# text-embedding-3-small의 입력 상한은 8191 토큰. tiktoken 없이 정확히 세지 못하므로 넉넉히
# 잡은 어림치로 자르고, 그래도 상한을 넘으면 아래에서 절반씩 줄여가며 재시도한다.
_EMBED_TOKEN_BUDGET = 7500


def _openai_client() -> OpenAI:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key or api_key == "your_openai_api_key_here":
        raise RuntimeError("OPENAI_API_KEY가 설정되지 않았습니다. backend/.env를 확인하세요.")
    return OpenAI(api_key=api_key, timeout=OPENAI_TIMEOUT_SECONDS)


def _estimate_tokens(text: str) -> float:
    """ASCII는 대략 4글자에 1토큰, 한글 같은 비ASCII는 글자당 2토큰으로 보수적으로 잡는다."""
    ascii_chars = sum(1 for ch in text if ord(ch) < 128)
    return ascii_chars / 4 + (len(text) - ascii_chars) * 2


def _truncate_for_embedding(text: str, budget: float = _EMBED_TOKEN_BUDGET) -> str:
    if _estimate_tokens(text) <= budget:
        return text
    # 어림치 기준으로 비율만큼 자른다 (정확할 필요는 없고, API 상한만 넘지 않으면 된다)
    ratio = budget / _estimate_tokens(text)
    return text[: max(1, int(len(text) * ratio))]


# _EMBED_TOKEN_BUDGET(7500)은 "OpenAI 임베딩 API 한 번 호출 상한"이지 검색 정밀도를 위한
# 청크 크기가 아니다 — 그보다 훨씬 작아야 청크 하나의 임베딩이 한 가지 내용에 집중된다.
# 예전엔 문서가 이 상한을 넘으면 _truncate_for_embedding으로 뒷부분을 그냥 잘라버렸는데,
# 그러면 벡터가 문서 앞부분만 대표하게 돼서 뒷부분 내용은 검색해도 안 걸렸다.
_CHUNK_TARGET_TOKENS = 1200
_CHUNK_OVERLAP_TOKENS = 150  # 청크 경계에서 문맥이 끊기는 걸 완화하려고 앞 청크 꼬리를 이어붙임


def _split_into_paragraphs(text: str) -> list[str]:
    return [p for p in re.split(r"\n\s*\n", text) if p.strip()]


def _hard_slice(text: str, budget_tokens: float) -> list[str]:
    """개행이 거의 없는 한 덩어리(압축된 코드 등)용 폴백 — 공백 기준으로 끊고,
    공백을 못 찾으면 비율 기반 강제 절단(_truncate_for_embedding과 동일한 방식)."""
    pieces, remaining = [], text
    while remaining:
        if _estimate_tokens(remaining) <= budget_tokens:
            pieces.append(remaining)
            break
        ratio = budget_tokens / _estimate_tokens(remaining)
        cut = max(1, int(len(remaining) * ratio))
        break_at = remaining.rfind(" ", 0, cut)
        if break_at <= 0:
            break_at = cut
        pieces.append(remaining[:break_at])
        remaining = remaining[break_at:].lstrip()
    return pieces


def _tail_by_tokens(text: str, budget_tokens: float) -> str:
    if budget_tokens <= 0 or _estimate_tokens(text) <= budget_tokens:
        return text
    ratio = budget_tokens / _estimate_tokens(text)
    return text[-max(1, int(len(text) * ratio)):]


def _chunk_text(
    text: str,
    target_tokens: float = _CHUNK_TARGET_TOKENS,
    overlap_tokens: float = _CHUNK_OVERLAP_TOKENS,
) -> list[str]:
    """target_tokens 이하면 그대로 [text] 하나(청크 분할 없음 — 대다수 문서가 이 경로).
    넘으면 문단(빈 줄) 경계를 우선 존중해 나누고, 문단 자체가 너무 길면(개행 없는 코드 등)
    공백 기준 강제 분할로 대체한다. 청크 사이엔 overlap_tokens만큼 앞 청크 꼬리를 이어
    붙여 문단 경계에서 문맥이 끊기는 걸 완화한다."""
    if _estimate_tokens(text) <= target_tokens:
        return [text]

    paragraphs = _split_into_paragraphs(text) or [text]
    units = []
    for p in paragraphs:
        units.extend(_hard_slice(p, target_tokens) if _estimate_tokens(p) > target_tokens else [p])

    chunks: list[str] = []
    current_parts: list[str] = []
    current_tokens = 0.0
    for unit in units:
        unit_tokens = _estimate_tokens(unit)
        if current_parts and current_tokens + unit_tokens > target_tokens:
            chunks.append("\n\n".join(current_parts))
            tail = _tail_by_tokens(chunks[-1], overlap_tokens)
            current_parts = [tail] if tail else []
            current_tokens = _estimate_tokens(tail) if tail else 0.0
        current_parts.append(unit)
        current_tokens += unit_tokens
    if current_parts:
        chunks.append("\n\n".join(current_parts))
    return chunks


class OpenAIDirectEmbeddings(Embeddings):
    """Chroma가 요구하는 최소 인터페이스(embed_documents/embed_query)만 직접 구현한 임베딩."""

    def __init__(self, model: str = EMBEDDING_MODEL, batch_size: int = 64):
        self.model = model
        self.batch_size = batch_size

    def _embed(self, texts: List[str]) -> List[List[float]]:
        client = _openai_client()
        vectors: List[List[float]] = []
        for start in range(0, len(texts), self.batch_size):
            batch = [_truncate_for_embedding(t) for t in texts[start:start + self.batch_size]]
            for attempt in range(5):
                try:
                    resp = client.embeddings.create(model=self.model, input=batch)
                    break
                except RateLimitError as e:
                    # 개별 요청 크기가 아니라 "분당 처리량(TPM)" 조직 전체 한도 초과 — 실사용 중
                    # GitHub 저장소 전체 색인처럼 한 번에 텍스트 양이 많을 때 실제로 겪었다.
                    # 이건 잘라도 소용없고 기다렸다 그대로 재시도해야 한다. 에러 메시지가
                    # "try again in 1.162s" 식으로 대기 시간을 알려주면 그걸 쓰고, 없으면
                    # 지수 백오프.
                    if attempt >= 4:
                        raise
                    match = re.search(r"try again in ([\d.]+)s", str(e))
                    wait = float(match.group(1)) if match else 2 ** attempt
                    time.sleep(wait + 0.5)
                    continue
                except Exception as e:
                    # 상한을 넘긴 경우엔 더 짧게 잘라 다시 시도(어림치가 빗나간 경우 대비) —
                    # 실제로 어림치 통과 후("under 7500 tokens") 진짜 토큰 수는 8192를 넘겨
                    # 그대로 실패한 사례 발생(GitHub 코드 파일, 한글 비중 높은 텍스트에서
                    # 문자당 토큰 어림치가 실제보다 낮게 잡힘). "maximum context length"
                    # 문구만 보던 걸 "maximum input length" 등 다른 표현도 잡게 넓혔다.
                    msg = str(e).lower()
                    if "maximum" in msg and "token" in msg and attempt < 4:
                        batch = [t[: max(1, len(t) // 2)] for t in batch]
                        continue
                    raise
            vectors.extend(item.embedding for item in resp.data)
        return vectors

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return self._embed(texts)

    def embed_query(self, text: str) -> List[float]:
        return self._embed([text])[0]


class OllamaDirectEmbeddings(Embeddings):
    """OpenAIDirectEmbeddings와 같은 최소 인터페이스를, 회사 내부망(또는 로컬)에 뜬 Ollama
    서버로 구현한 버전. 문서 내용이 외부로 전혀 나가지 않는다는 게 유일한 차이이고, Chroma
    입장에서는 두 구현을 구분할 필요가 없다 — embed_documents/embed_query만 맞으면 된다."""

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return llm_backend.ollama_embed_texts([_truncate_for_embedding(t) for t in texts])

    def embed_query(self, text: str) -> List[float]:
        return llm_backend.ollama_embed_texts([_truncate_for_embedding(text)])[0]


# LLM_BACKEND 환경변수(기본값 openai)로 전환 — llm_backend.py 모듈 docstring 참고.
embeddings = OllamaDirectEmbeddings() if llm_backend.is_ollama_backend() else OpenAIDirectEmbeddings()

# 2. Chroma DB 세팅 (로컬 디스크에 저장) — DB_PATH와 같은 이유로 CHROMA_PERSIST_DIR도
# 환경변수로 덮어쓸 수 있게 한다(Render 등에서 영구 디스크 마운트 경로를 가리키기 위함).
CHROMA_PERSIST_DIR = os.getenv("CHROMA_PERSIST_DIR") or "./chroma_db"

def get_vectorstore():
    # 저장된 DB가 있으면 불러오고, 없으면 새로 만듭니다.
    return Chroma(
        collection_name="topic_documents",
        embedding_function=embeddings,
        persist_directory=CHROMA_PERSIST_DIR
    )

def synced_by_set(value: Optional[str]) -> set[str]:
    """syncedBy 메타데이터 문자열(",1,3,")을 사용자 id 집합으로 푼다."""
    return {part for part in (value or "").split(",") if part}


def synced_by_str(user_ids: set[str]) -> str:
    """사용자 id 집합을 syncedBy 메타데이터 문자열로 만든다. 앞뒤에 콤마를 붙여두면
    ",10," 같은 부분 문자열 검색으로 id 1과 10을 헷갈리지 않고 판정할 수 있다."""
    return "," + ",".join(sorted(user_ids)) + "," if user_ids else ""


def _load_existing_metadata(vectorstore, ids: list[str]) -> dict[str, dict]:
    """이미 색인된 문서들의 메타데이터를 id로 조회한다 (없는 id는 결과에서 빠진다)."""
    if not ids:
        return {}
    try:
        got = vectorstore._collection.get(ids=ids, include=["metadatas"])
    except Exception as e:
        print(f"기존 메타데이터 조회 실패(새로 적재로 진행): {e}")
        return {}
    return {
        doc_id: (meta or {})
        for doc_id, meta in zip(got.get("ids", []), got.get("metadatas", []))
    }


def content_hash(title: str, content: str) -> str:
    """본문이 실제로 바뀌었는지 판정하는 지문. 원본의 수정 시각이 부정확하거나(Slack 묶음처럼)
    아예 없을 때도 불필요한 재임베딩을 막아준다."""
    return hashlib.sha256(f"{title}\n{content}".encode("utf-8")).hexdigest()


def ingest_documents(source_docs: list[dict], synced_by_user_id: Optional[int] = None) -> int:
    """공통 문서 포맷(dict) 리스트를 임베딩해 Vector DB에 적재하고, **실제로 임베딩한 문서 수**를
    반환한다 (내용이 그대로인 문서는 임베딩을 건너뛰므로 0일 수 있다).

    source_docs의 각 항목은 dummy_data.mock_documents와 같은 형태
    (id, title, source, author, date, content 등)를 따라야 합니다.

    synced_by_user_id를 주면 "이 문서를 가져온 사람" 목록(syncedBy)에 그 사용자를 추가한다.
    같은 저장소를 여러 사람이 연동할 수 있으므로 덮어쓰지 않고 기존 목록과 합친다. 이 값이
    대시보드 통계 범위 제한과 연동 해제 시 정리의 기준이 된다.
    """
    if not source_docs:
        return 0

    # API Key 검증 — ollama 백엔드는 OpenAI 키가 필요 없다
    if not llm_backend.is_ollama_backend():
        if not os.getenv("OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY") == "your_openai_api_key_here":
            print("OPENAI_API_KEY가 설정되지 않아 임베딩을 진행할 수 없습니다. .env 파일을 확인해 주세요.")
            return 0

    vectorstore = get_vectorstore()
    base_ids = [doc['id'] for doc in source_docs]
    # 문서가 여러 청크로 쪼개져도 chunk-0의 id == base_id라, 여기 한 번 조회로 문서 단위
    # contentHash/chunkCount 등 "대표" 메타데이터를 전부 얻을 수 있다.
    existing = _load_existing_metadata(vectorstore, base_ids)

    docs_to_embed = []
    ids_to_embed = []
    metadata_only_ids = []
    metadata_only_values = []
    stale_ids_to_delete = []
    embedded_base_ids = set()

    for doc in source_docs:
        base_id = doc['id']
        prev = existing.get(base_id, {})
        owners = synced_by_set(prev.get("syncedBy"))
        if synced_by_user_id is not None:
            owners.add(str(synced_by_user_id))

        digest = content_hash(doc['title'], doc['content'])
        if prev and prev.get("contentHash") == digest:
            # 내용이 그대로면 임베딩을 다시 하지 않는다 (비용의 대부분이 여기서 절약된다).
            # 다만 다른 사람이 같은 문서를 새로 연동했다면 syncedBy만 갱신해준다 — 청크로
            # 쪼개진 문서라면 모든 형제 청크 행에 반영해야 한다(대표 행만 갱신하면, 통계/검색이
            # 다른 청크 행을 대표로 고를 때 소유권이 낡은 채로 보일 수 있다).
            new_synced = synced_by_str(owners)
            if prev.get("syncedBy") != new_synced:
                chunk_count = int(prev.get("chunkCount", 1))
                for i in range(chunk_count):
                    sib_id = base_id if i == 0 else f"{base_id}::chunk-{i}"
                    metadata_only_ids.append(sib_id)
                    metadata_only_values.append({**prev, "id": sib_id, "chunkIndex": i, "syncedBy": new_synced})
            continue

        # 문서가 클 때만 여러 청크로 쪼갠다 — 대다수 문서는 그대로 1개 청크([text])라 아래
        # 루프가 기존과 동일하게 딱 1개 행만 만든다.
        chunks = _chunk_text(doc['content'])
        chunk_count = len(chunks)
        old_chunk_count = int(prev.get("chunkCount", 1)) if prev else 0
        if old_chunk_count > chunk_count:
            # 재청크로 청크 수가 줄었다(문서가 짧아짐) — 남는 뒤쪽 청크 행은 아래에서 새
            # 청크들을 upsert한 "다음에" 지운다(먼저 지우면 임베딩이 도는 동안 검색 공백이
            # 생긴다 — add_documents가 delete 없이 upsert인 이유와 같은 원칙).
            stale_ids_to_delete.extend(
                base_id if i == 0 else f"{base_id}::chunk-{i}"
                for i in range(chunk_count, old_chunk_count)
            )

        synced = synced_by_str(owners)
        for i, chunk in enumerate(chunks):
            chunk_id = base_id if i == 0 else f"{base_id}::chunk-{i}"
            # 벡터 검색을 위해 검색할 텍스트 덩어리(page_content) 생성 — 이 청크 슬라이스만 담음
            page_content = f"Title: {doc['title']}\n\nContent:\n{chunk}"

            # content는 항상 전체 원문(청크로 안 잘림) — 모든 형제 청크 행에 동일하게 중복
            # 저장해서, 검색 결과 표시/AI 요약/통계 등은 청크 중 아무거나 하나를 대표로 삼아도
            # 항상 문서 전체를 보게 된다(page_content는 "Title: ...\n\nContent:\n..." 형태라
            # 그대로 스니펫으로 쓰면 임베딩용 접두사가 노출되기 때문에 원본 본문을 따로 둔다).
            metadata = {
                "id": chunk_id,
                "baseId": base_id,
                "chunkIndex": i,
                "chunkCount": chunk_count,
                "title": doc['title'],
                "source": doc['source'],
                "author": doc['author'],
                "date": doc['date'],
                "content": doc['content'],
                # Chroma 메타데이터는 리스트를 못 담아서 콤마로 join, 조회 시 다시 split
                "tags": ",".join(doc.get('tags', [])),
                "sourceUrl": doc.get('sourceUrl', ''),
                "syncedBy": synced,
                "contentHash": digest,
                # 원본이 마지막으로 수정된 시각 — 다음 동기화 때 "이 문서는 안 바뀌었으니 본문을
                # 다시 받아올 필요도 없다"를 커넥터가 판단하는 기준
                "sourceUpdatedAt": doc.get("sourceUpdatedAt", ""),
            }

            docs_to_embed.append(Document(page_content=page_content, metadata=metadata))
            ids_to_embed.append(chunk_id)
        embedded_base_ids.add(base_id)

    if metadata_only_ids:
        try:
            vectorstore._collection.update(ids=metadata_only_ids, metadatas=metadata_only_values)
        except Exception as e:
            print(f"메타데이터 갱신 실패: {e}")

    if docs_to_embed:
        # add_documents(ids=...)는 내부적으로 Chroma의 upsert를 쓰므로 같은 id로 다시 넣으면
        # 덮어쓴다 — 예전엔 먼저 delete를 했는데, 임베딩이 도는 수초~수분 동안 그 문서들이
        # 검색에서 사라지는 구간이 생겨서 없앴다.
        vectorstore.add_documents(docs_to_embed, ids=ids_to_embed)
        print(f"문서 {len(embedded_base_ids)}개({len(docs_to_embed)}개 청크)를 새로 임베딩했습니다 "
              f"(변경 없음: {len(source_docs) - len(embedded_base_ids)}개).")

    if stale_ids_to_delete:
        try:
            vectorstore.delete(ids=stale_ids_to_delete)
        except Exception as e:
            print(f"오래된 청크 정리 실패: {e}")

    # 청크 행 수가 아니라 "실제로 임베딩한 문서 수" — sync-status의 lastCount가 사용자에게
    # "N개 문서 동기화"로 보이므로, 청크 행 수를 반환하면 큰 파일 하나가 "5개 문서 동기화"처럼
    # 오해를 부른다.

    # 동기화된 문서의 author들을 workspace_authors 로스터에 누적한다.
    # 소스별로 묶어서 한 번씩만 호출해 DB 왕복을 줄인다.
    if source_docs:
        source_to_authors: dict[str, list[str]] = {}
        for d in source_docs:
            src = d.get("source", "")
            author = d.get("author", "").strip()
            if src and author and author != "알 수 없음":
                source_to_authors.setdefault(src, []).append(author)
        for src_name, names in source_to_authors.items():
            try:
                db.upsert_workspace_authors(list(set(names)), source=src_name)
            except Exception as e:
                print(f"workspace_authors 누적 실패({src_name}): {e}")

    return len(embedded_base_ids)



def ingest_mock_documents():
    """초기 세팅 시 더미 문서들을 Vector DB에 적재합니다."""
    print("문서 임베딩 및 DB 적재를 시작합니다... (source: mock)")
    ingest_documents(mock_documents)


def ingest_notion_documents():
    """Notion 통합에 공유된 페이지들을 읽어와 Vector DB에 적재합니다."""
    from connectors.notion_connector import fetch_notion_documents

    print("Notion 페이지를 가져오는 중...")
    docs = fetch_notion_documents()
    print(f"Notion에서 {len(docs)}개의 페이지를 가져왔습니다. 임베딩을 시작합니다... (source: notion)")
    ingest_documents(docs)


def ingest_slack_documents():
    """봇이 속한 Slack 채널의 최근 대화를 읽어와 Vector DB에 적재합니다."""
    from connectors.slack_connector import fetch_slack_documents

    print("Slack 대화를 가져오는 중...")
    docs = fetch_slack_documents()
    print(f"Slack에서 {len(docs)}개의 문서를 만들었습니다. 임베딩을 시작합니다... (source: slack)")
    ingest_documents(docs)


def ingest_gdrive_documents():
    """서비스 계정에 공유된 Google Docs를 읽어와 Vector DB에 적재합니다."""
    from connectors.gdrive_connector import fetch_gdrive_documents

    print("Google Drive 문서를 가져오는 중...")
    docs = fetch_gdrive_documents()
    print(f"Google Drive에서 {len(docs)}개의 문서를 가져왔습니다. 임베딩을 시작합니다... (source: gdrive)")
    ingest_documents(docs)


def ingest_github_documents():
    """GITHUB_REPOS에 지정된 저장소의 Issue/PR을 읽어와 Vector DB에 적재합니다."""
    from connectors.github_connector import fetch_github_documents

    print("GitHub Issue/PR을 가져오는 중...")
    docs = fetch_github_documents()
    print(f"GitHub에서 {len(docs)}개의 문서를 만들었습니다. 임베딩을 시작합니다... (source: github)")
    ingest_documents(docs)


def ingest_gitlab_documents():
    """GITLAB_PROJECTS에 지정된 프로젝트의 Issue/MR을 읽어와 Vector DB에 적재합니다."""
    from connectors.gitlab_connector import fetch_gitlab_documents

    print("GitLab Issue/MR을 가져오는 중...")
    docs = fetch_gitlab_documents()
    print(f"GitLab에서 {len(docs)}개의 문서를 만들었습니다. 임베딩을 시작합니다... (source: gitlab)")
    ingest_documents(docs)


# provider(계정 연동 이름) → 그 사람 본인 토큰으로 문서를 가져오는 함수. .env에 관리자가
# 미리 정해둔 고정 목록(위 ingest_*_documents들) 대신, 계정을 연동한 시점에 그 사람이 실제
# 접근 가능한 콘텐츠 전체를 대상으로 삼기 위한 것 (PRD "계정 연동 = 내 문서 전부 검색" 요구사항).
_USER_FETCHERS = {}


def _get_user_fetchers() -> dict:
    if not _USER_FETCHERS:
        from connectors.github_connector import fetch_github_documents_for_user
        from connectors.gitlab_connector import fetch_gitlab_documents_for_user
        from connectors.slack_connector import fetch_slack_documents_for_user
        from connectors.notion_connector import fetch_notion_documents_for_user
        from connectors.gdrive_connector import fetch_gdrive_documents_for_user

        _USER_FETCHERS.update({
            "github": fetch_github_documents_for_user,
            "gitlab": fetch_gitlab_documents_for_user,
            "slack": fetch_slack_documents_for_user,
            "notion": fetch_notion_documents_for_user,
            "google": fetch_gdrive_documents_for_user,
        })
    return _USER_FETCHERS


# provider(계정 연동 이름) → 문서 메타데이터의 source 값
PROVIDER_SOURCES = {
    "github": "github",
    "gitlab": "gitlab",
    "slack": "slack",
    "notion": "notion",
    "google": "gdrive",
}


def _known_documents(source: str, user_id: Optional[int]) -> dict[str, str]:
    """이 사용자가 이 소스로 이미 가져와둔 문서들의 {id: sourceUpdatedAt}.
    커넥터는 이걸 보고 "원본이 그대로면 본문을 다시 받지 않는다"를 판단한다."""
    if user_id is None:
        return {}
    try:
        got = get_vectorstore()._collection.get(where={"source": source}, include=["metadatas"])
    except Exception as e:
        print(f"기존 문서 목록 조회 실패(전체 수집으로 진행): {e}")
        return {}

    marker = str(user_id)
    known = {}
    for meta in got.get("metadatas", []) or []:
        if not meta or marker not in synced_by_set(meta.get("syncedBy")):
            continue
        # baseId 기준으로 모아야 한다 — 커넥터가 돌려주는 seen_ids는 항상 base id뿐이라,
        # 여기서 청크 접미사 id를 그대로 담으면 다음 동기화 때 절대 안 겹쳐서 청크로 쪼개진
        # 문서가 매번 "원본에서 사라진 문서"로 오인되어 지워진다. dict라 여러 청크 행이
        # base_id 하나로 자연스럽게 합쳐지므로 별도 중복 제거는 필요 없다.
        base_id = meta.get("baseId") or meta.get("id", "")
        if not base_id:
            continue
        known[base_id] = meta.get("sourceUpdatedAt", "") or ""
    return known


def _prune_missing_documents(missing_base_ids: list[str], user_id: int) -> int:
    """원본에서 사라진(삭제됐거나 접근 권한을 잃은) 문서에서 이 사용자를 떼어낸다.
    아무도 안 가져오는 문서가 되면 컬렉션에서 완전히 지운다. 이게 없으면 삭제된 Drive 파일이나
    이름이 바뀐 저장소의 이슈가 영원히 검색에 남는다.

    missing_base_ids는 base id(청크 접미사 없음)다 — 문서가 여러 청크로 쪼개져 있으면 형제
    청크 행 전부를 같이 갱신/삭제해야 한다(대표 chunk-0 행만 지우면 나머지 청크 행이 영원히
    고아로 남는다)."""
    if not missing_base_ids:
        return 0

    vectorstore = get_vectorstore()
    existing = _load_existing_metadata(vectorstore, missing_base_ids)  # chunk-0 대표 조회
    to_delete = []
    update_ids, update_metas = [], []

    for base_id, meta in existing.items():
        owners = synced_by_set(meta.get("syncedBy"))
        owners.discard(str(user_id))
        chunk_count = int(meta.get("chunkCount", 1))
        sibling_ids = [base_id if i == 0 else f"{base_id}::chunk-{i}" for i in range(chunk_count)]
        if owners:
            new_synced = synced_by_str(owners)
            for i, sib_id in enumerate(sibling_ids):
                update_ids.append(sib_id)
                update_metas.append({**meta, "id": sib_id, "chunkIndex": i, "syncedBy": new_synced})
        else:
            to_delete.extend(sibling_ids)

    try:
        if update_ids:
            vectorstore._collection.update(ids=update_ids, metadatas=update_metas)
        if to_delete:
            vectorstore.delete(ids=to_delete)
    except Exception as e:
        print(f"사라진 문서 정리 실패: {e}")
        return 0

    return len(missing_base_ids)


def remove_user_documents(provider: str, user_id: int) -> int:
    """연동 해제 시, 그 사용자가 이 소스로 가져왔던 문서를 전부 정리한다.
    같은 문서를 다른 사람도 연동해뒀다면 그 사람 몫으로는 그대로 남는다."""
    source = PROVIDER_SOURCES.get(provider, provider)
    known = _known_documents(source, user_id)
    return _prune_missing_documents(list(known), user_id)


# provider별 최근 동기화 상태 — 연동 직후 백그라운드 수집이나 15분 주기 재동기화가 지금
# 진행 중인지, 마지막 결과가 어땠는지를 프론트가 /api/v1/sync-status로 폴링해서 진행률
# 표시에 쓴다. 여러 스레드(연동 직후 백그라운드 스레드, 주기 재동기화)가 동시에 건드릴 수
# 있어서 락으로 보호한다. 프로세스 재시작하면 초기화되는 휘발성 상태 — DB에 영속할 필요는
# 없다(길어야 몇 분짜리 진행 상황일 뿐이라).
_sync_status: dict[tuple[int, str], dict] = {}
_sync_status_lock = threading.Lock()


def _set_sync_status(user_id: int, provider: str, **fields) -> None:
    with _sync_status_lock:
        key = (user_id, provider)
        current = dict(_sync_status.get(key, {}))
        current.update(fields)
        _sync_status[key] = current


def get_sync_status(user_id: int) -> dict[str, dict]:
    """이 사용자가 연동한 소스별 최근 동기화 상태(provider -> {status, lastCount, ...})."""
    with _sync_status_lock:
        return {provider: dict(v) for (uid, provider), v in _sync_status.items() if uid == user_id}


def sync_documents_for_user(provider: str, access_token: str, user_id: Optional[int] = None) -> int:
    """계정을 연동한 사람 본인의 access token으로, 그 사람이 실제 접근 가능한 문서 전체를
    가져와 Vector DB에 반영한다. API 서버와 같은 프로세스 안에서 바로 실행되므로, 오프라인
    스크립트와 달리 서버 재시작 없이 바로 검색에 반영된다.

    증분 방식이다 — 목록 조회는 매번 하지만(사라진 문서를 알아내야 하므로) 본문을 다시 받아와
    임베딩하는 건 원본이 실제로 바뀐 문서뿐이다. 반환값은 **새로 임베딩한 문서 수**.

    user_id는 문서의 syncedBy(누가 가져온 문서인지)에 기록돼, 대시보드 통계 범위 제한과
    연동 해제 시 정리의 기준이 된다. user_id가 있으면 진행 상태도 함께 기록한다(get_sync_status)."""
    fetcher = _get_user_fetchers().get(provider)
    if not fetcher:
        return 0

    if user_id is not None:
        _set_sync_status(user_id, provider, status="running", startedAt=datetime.now(timezone.utc).isoformat())

    try:
        source = PROVIDER_SOURCES.get(provider, provider)
        known = _known_documents(source, user_id)
        docs, seen_ids = fetcher(access_token, known)
        embedded = ingest_documents(docs, synced_by_user_id=user_id)

        if user_id is not None:
            missing = [doc_id for doc_id in known if doc_id not in seen_ids]
            if missing and not seen_ids:
                # 원본에서 아무것도 못 봤다는 건 "전부 삭제됐다"기보다 수집이 실패했다는 뜻일
                # 가능성이 훨씬 높다. 이럴 때 정리를 돌리면 멀쩡한 문서를 통째로 날린다.
                print(
                    f"{source} 수집 결과가 비어 있어 이번 주기 정리는 건너뜁니다 "
                    f"(기존 문서 {len(known)}개 유지)."
                )
            else:
                pruned = _prune_missing_documents(missing, user_id)
                if pruned:
                    print(f"원본에서 사라진 {source} 문서 {pruned}개를 정리했습니다.")
    except Exception as e:
        if user_id is not None:
            _set_sync_status(
                user_id, provider, status="error", error=str(e),
                finishedAt=datetime.now(timezone.utc).isoformat(),
            )
        raise  # 호출자(연동 직후 백그라운드 스레드, 자동 재동기화 루프)가 그대로 처리하던 대로 유지
    else:
        if user_id is not None:
            _set_sync_status(
                user_id, provider, status="done", lastCount=embedded, error=None,
                finishedAt=datetime.now(timezone.utc).isoformat(),
            )
        return embedded


# 3. LLM 요약 프롬프트 셋업
# 출력 형식은 응답 스키마(models.Summary)에서 직접 뽑아 프롬프트에 박아 넣는다.
prompt_template = """
당신은 사내 지식 관리 AI 어시스턴트입니다.
사용자의 질문에 답하기 위해, 아래 제공된 검색된 문서(Context)들을 분석하고 요약하세요.

[사용자 질문]
{query}

[검색된 문서들 (Context)]
{context}
{known_people_section}
{doc_authors_section}
{roster_section}
[지시사항]
위 문서들을 바탕으로 다음 정보를 추출하여 반드시 JSON 형식으로 응답하세요.
1. keyPoints: 전체 문서의 핵심 내용을 3-4개의 문장으로 요약한 리스트
2. decisionTrail: 시간 순서대로 의사결정의 흐름을 나타내는 리스트. (date, decision, source 포함)
3. actionItems: 문맥상 아직 완료되지 않았거나 진행 중인 할 일 리스트. (id, task, assignee, dueDate, status, source 포함)
   task는 "~한 영역과 ~을 구분" 같은 문서 요약 명사구가 아니라, 실제로 할 일을 지시하는 간결한
   명령형 문장으로 쓰세요 (예: "API 응답 속도 테스트하기", "디자인 시안 최종 검토받기"). 15단어를
   넘지 않게 하고, 누가 봐도 바로 무엇을 해야 하는지 알 수 있어야 합니다.
   역할·업무 분담(예: "제가 백엔드 맡을게요", "프론트는 승현님께 부탁드릴게요")은 "이미 정해진
   결정"이라고만 decisionTrail에 적고 끝내지 마세요 — 그 역할을 맡은 사람에게는 아직 실제로
   그 일을 시작/완료했다는 언급이 없는 한, "(그 역할) 시작하기" 형태의 actionItem도 반드시
   같이 만드세요. 한 사람이 맡겠다고 말하고 다른 사람에게 부탁하는 대화라면, 둘 다 각자의
   할 일로 나와야 합니다 — 부탁받은 사람 것만 뽑고 자원한 사람 것은 빠뜨리지 마세요.
   status 값은 반드시 "pending", "in-progress", "completed" 셋 중 하나의 영문 문자열이어야 합니다
   (한국어로 쓰지 마세요 — 우리 시스템이 이 값으로 상태를 순환시킵니다).
   decisionTrail과 actionItems의 source 값은 반드시 그 근거가 된 문서의 "문서 출처: " 뒤에 적힌
   값(예: notion, slack, gdrive, github, gitlab)을 그대로 사용하세요. 문서 제목이나 다른 설명을
   적지 마세요.
   assignee(담당자)는 반드시 아래 우선순위로 정하세요 — 회의/문서 작성자가 매번 자기 이름을
   말하거나 태그하지 않아도 되도록, 있는 정보 안에서 최대한 합리적으로 추론하는 것이 목표입니다.
   a) 문서/대화 내용 안에서 특정 사람이 그 일을 하겠다고 직접 말했거나(예: "제가 할게요"),
      다른 사람이 그 사람을 지목했다면(예: "@이지영님 부탁드려요") 그 사람 이름을 쓰세요.
   b) 그런 명시적 언급이 없다면, 그 근거가 된 문서의 "문서 작성자" 값을 담당자로 쓰세요
      (예: Slack 메시지라면 그 메시지를 쓴 사람, 문서라면 그 문서를 쓴 사람이 기본 담당자).
   c) 문서 작성자도 불분명하거나 여러 사람이 섞여 있어 특정하기 어려우면 "미정"이라고 쓰세요.
      절대로 문서에 등장하지 않는 이름을 지어내지 마세요.
   d) 이름이 성 없이 이름만(예: "승현님") 나오면, 아래 세 후보 목록을 이 순서 그대로 확인하세요.
      1) 먼저 [알려진 사람 목록](사용자가 직접 등록한 정식 이름+별칭 사전)에서 별칭이 일치하는
         사람을 모두 찾으세요.
         - 정확히 한 명과만 일치하면 그 사람의 정식 이름(canonical name)을 담당자로 쓰고, 2)는
           확인하지 않습니다.
         - 두 명 이상과 동시에 일치하면, 목록에 먼저 나온 사람을 임의로 고르지 말고 대화에 나온
           표현 그대로("승현님") 쓰고 더 이상 진행하지 않습니다.
      2) [알려진 사람 목록]이 비어 있거나 일치하는 사람이 아예 없을 때만, [문서 작성자 후보]
         목록(이번 검색 결과 문서들에 실제로 등장한 전체 이름 — 별도 등록 없이 문서에서 자동으로
         뽑힌 것)에서 그 짧은 이름을 부분 문자열로 포함하는 전체 이름을 찾으세요(예: "승현"은
         "송승현"과 "이승현"을 둘 다 포함).
         - 정확히 한 명의 전체 이름과만 일치하면 그 전체 이름을 담당자로 쓰세요.
         - 두 명 이상의 전체 이름과 동시에 일치하거나, 이 목록에도 일치하는 사람이 없으면 3)으로
           넘어가세요.
      3) [문서 작성자 후보]에도 없을 때만, [워크스페이스 인물 로스터](이번 검색에 안 잡힌 문서의
         작성자까지 포함한 워크스페이스 전체 이름 목록)에서 그 짧은 이름을 부분 문자열로 포함하는
         전체 이름을 찾으세요.
         - 정확히 한 명의 전체 이름과만 일치하면 그 전체 이름을 담당자로 쓰세요.
         - 두 명 이상과 동시에 일치하거나 이 목록에도 없으면, 대화에 나온 표현 그대로("승현님")
           쓰세요.
      **세 목록 모두, 후보가 둘 이상으로 겹칠 때 임의로 한 명을 찍어 정규화하는 것은 항상
      "원문 표현 그대로 남겨두는 것"보다 나쁩니다** — 어느 한 명을 찍으면 실제로는 다른 사람의
      할 일이 엉뚱한 사람에게 배정되는 것이기 때문입니다. [문서 작성자 후보]와 [워크스페이스
      인물 로스터]는 [알려진 사람 목록]과 달리 등록된 별칭이 없는 "전체 이름 그대로"인 목록이라는
      점도 유의하세요 — 부분 문자열 포함 여부로만 판단하고, 비슷하게 들린다고 다른 이름을
      추측해서 매칭하지 마세요.

[형식 지침]
응답은 반드시 아래의 JSON 스키마를 따라야 하며, 마크다운 코드블록 없이 순수 JSON 문자열만 반환하세요.
status를 제외한 모든 텍스트 값(title, keyPoints, decision, task 등)은 반드시 한국어로 작성하세요.
{format_instructions}
"""

_STATUS_ALIASES = {
    "완료": "completed", "완료됨": "completed", "done": "completed",
    "진행 중": "in-progress", "진행중": "in-progress", "in progress": "in-progress",
    "대기": "pending", "대기 중": "pending", "미완료": "pending",
}


def _normalize_status(status: str) -> str:
    """LLM이 지시를 어기고 한국어 등 다른 표현으로 status를 반환하는 경우를 대비한 안전망.
    (예: "진행 중" → "in-progress") 우리 상태 순환 로직(pending→in-progress→completed)이
    영문 3값만 인식하기 때문에 필요하다."""
    normalized = status.strip().lower()
    if normalized in ("pending", "in-progress", "completed"):
        return normalized
    return _STATUS_ALIASES.get(status.strip(), "pending")

def generate_ai_summary(
    query: str,
    retrieved_docs: List[Document],
    api_key: str = None,
    known_people: Optional[List[dict]] = None,
    workspace_authors: Optional[List[str]] = None,
) -> Optional[dict]:
    """검색된 문서들을 바탕으로 LLM을 호출하여 요약 JSON을 반환합니다.

    실패하면 None을 반환한다 — 예전엔 mock 요약(dummy_data)을 대신 돌려줬는데, 사용자 입장에서는
    진짜 요약과 구분할 방법이 없고 그 가짜 액션아이템이 할 일 리스트에 저장되기까지 했다.
    실패는 실패로 알리는 게 맞다."""

    # 1. API 키 확인 — ollama 백엔드는 OpenAI 키가 필요 없다(로컬/사내망 모델을 그대로 호출)
    use_ollama = llm_backend.is_ollama_backend()
    actual_api_key = api_key or os.getenv("OPENAI_API_KEY")
    if not use_ollama and (not actual_api_key or actual_api_key == "your_openai_api_key_here"):
        print("OPENAI_API_KEY가 설정되지 않아 요약을 생성할 수 없습니다.")
        return None

    try:
        # 2. Context 구성 (담당자 추론 시 기본값으로 쓸 수 있도록 문서 작성자도 함께 전달)
        context_str = "\n\n---\n\n".join(
            [
                f"문서 출처: {doc.metadata.get('source', 'unknown')}\n"
                f"문서 작성자: {doc.metadata.get('author', '알 수 없음')}\n"
                f"{doc.page_content}"
                for doc in retrieved_docs
            ]
        )

        # 2b. 알려진 사람 목록 (동명이인 정규화용) — 비어 있으면 섹션 자체를 생략한다
        known_people_section = ""
        if known_people:
            people_lines = "\n".join(
                f"- {p['display_name']} (별칭: {', '.join(p['aliases'])})"
                for p in known_people
                if p.get("aliases")
            )
            if people_lines:
                known_people_section = f"\n[알려진 사람 목록]\n{people_lines}\n"

        # 2c. 문서 작성자 후보 — 사용자가 [알려진 사람 목록]에 별도로 등록해두지 않은 사람도,
        # 이번 검색 결과 문서에 실명이 이미 등장했다면 "짧은 이름 → 전체 이름" 매칭 후보로 쓸 수
        # 있다(별칭 사전을 매번 수동으로 채워야만 동명이인이 풀리던 한계 보완, PRD "오픈 이슈"
        # 참고). [알려진 사람 목록]에 이미 정식 이름으로 등록된 사람은 중복 표시하지 않는다.
        known_names = {p["display_name"] for p in (known_people or [])}
        doc_authors = sorted({
            author
            for doc in retrieved_docs
            if (author := doc.metadata.get("author", "").strip())
            and author not in ("알 수 없음", "")
            and author not in known_names
        })[:20]
        doc_authors_section = (
            f"\n[문서 작성자 후보] (이번 검색 결과에 실제로 등장한 이름 — 등록된 별칭 없음)\n"
            + "\n".join(f"- {name}" for name in doc_authors) + "\n"
        ) if doc_authors else ""
        # 2d. 워크스페이스 전체 인물 로스터 — 이번 검색에 안 잡힌 문서의 작성자도 포함하는
        # 전체 이름 목록. 동기화가 누적해온 워크스페이스 전체 이름으로 구성된다
        # (PRD §7 "워크스페이스 전체 인물 로스터" 오픈 이슈 구현).
        # [알려진 사람 목록]이나 [문서 작성자 후보]에 이미 있는 이름은 중복 제외한다.
        all_candidate_names = known_names | set(doc_authors)
        roster_names = sorted(
            name for name in (workspace_authors or [])
            if name not in all_candidate_names
        )[:50]  # 프롬프트 토큰 사용량을 줄이기 위해 50명 제한
        roster_section = (
            f"\n[워크스페이스 인물 로스터] (이번 검색에 안 잡힌 문서 작성자 포함 전체 이름 — 부분 문자열 매칭용)\n"
            + "\n".join(f"- {name}" for name in roster_names) + "\n"
        ) if roster_names else ""

        # 3. LLM 호출 — 어느 백엔드든 "JSON 문자열을 강제로 뱉게 한다"는 계약은 같아서
        # 이후(스키마 검증 등) 코드는 백엔드와 무관하게 동일하다.
        prompt = prompt_template.format(
            query=query,
            context=context_str,
            known_people_section=known_people_section,
            doc_authors_section=doc_authors_section,
            roster_section=roster_section,
            format_instructions=json.dumps(Summary.model_json_schema(), ensure_ascii=False),
        )
        print(f"LLM 호출 중... (검색된 문서 {len(retrieved_docs)}개 기반, backend={'ollama' if use_ollama else 'openai'})")
        if use_ollama:
            result = llm_backend.ollama_chat_json(prompt)
        else:
            client = OpenAI(api_key=actual_api_key, timeout=OPENAI_TIMEOUT_SECONDS)
            completion = client.chat.completions.create(
                model=SUMMARY_MODEL,
                temperature=0,
                response_format={"type": "json_object"},
                messages=[{"role": "user", "content": prompt}],
            )
            result = json.loads(completion.choices[0].message.content)

        # 응답 스키마에 맞는지 확인 (안 맞으면 에러 발생 → 요약 실패로 처리)
        validated_summary = Summary(**result)
        summary_dict = validated_summary.model_dump()
        for item in summary_dict.get("actionItems", []):
            item["status"] = _normalize_status(item.get("status", "pending"))
        return summary_dict

    except Exception as e:
        print(f"LLM 호출 중 에러 발생: {e}")
        return None

if __name__ == "__main__":
    import argparse

    parser_cli = argparse.ArgumentParser(description="Vector DB에 문서를 적재합니다.")
    parser_cli.add_argument(
        "--source", choices=["mock", "notion", "slack", "gdrive", "github", "gitlab"], default="mock",
        help="적재할 데이터 소스 (기본값: mock)"
    )
    args = parser_cli.parse_args()

    if args.source == "notion":
        ingest_notion_documents()
    elif args.source == "slack":
        ingest_slack_documents()
    elif args.source == "gdrive":
        ingest_gdrive_documents()
    elif args.source == "github":
        ingest_github_documents()
    elif args.source == "gitlab":
        ingest_gitlab_documents()
    else:
        ingest_mock_documents()
