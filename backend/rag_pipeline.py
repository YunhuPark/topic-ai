import os
import sys
from typing import List
from dotenv import load_dotenv

# Set ENV vars before importing to optimize load if needed
os.environ["TOKENIZERS_PARALLELISM"] = "false"
load_dotenv()

# Windows 콘솔(cp949)에서 이모지 print가 UnicodeEncodeError를 던지는 것 방지
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from langchain_core.documents import Document
from langchain_community.vectorstores import Chroma
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from pydantic import BaseModel, Field

from dummy_data import mock_documents
from models import Summary, DecisionTrailItem, ActionItem

# 1. 임베딩 모델 설정 (PyTorch 오류 방지를 위해 OpenAI 임베딩으로 전환)
embeddings = OpenAIEmbeddings(model="text-embedding-3-small")

# 2. Chroma DB 세팅 (로컬 디스크에 저장)
CHROMA_PERSIST_DIR = "./chroma_db"

def get_vectorstore():
    # 저장된 DB가 있으면 불러오고, 없으면 새로 만듭니다.
    return Chroma(
        collection_name="topic_documents",
        embedding_function=embeddings,
        persist_directory=CHROMA_PERSIST_DIR
    )

def ingest_documents(source_docs: list[dict]):
    """공통 문서 포맷(dict) 리스트를 임베딩해 Vector DB에 적재합니다.

    source_docs의 각 항목은 dummy_data.mock_documents와 같은 형태
    (id, title, source, author, date, content 등)를 따라야 합니다.
    """
    if not source_docs:
        print("적재할 문서가 없습니다.")
        return

    # API Key 검증
    if not os.getenv("OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY") == "your_openai_api_key_here":
        print("⚠️ OPENAI_API_KEY가 설정되지 않아 임베딩을 진행할 수 없습니다. .env 파일을 확인해 주세요.")
        return

    docs = []
    for doc in source_docs:
        # 벡터 검색을 위해 검색할 텍스트 덩어리(page_content) 생성
        page_content = f"Title: {doc['title']}\n\nContent:\n{doc['content']}"

        # 원본 메타데이터 보존 (content도 함께 저장 — page_content는 "Title: ...\n\nContent:\n..."
        # 형태라 그대로 스니펫으로 쓰면 임베딩용 접두사가 노출되기 때문에 원본 본문을 따로 둔다)
        metadata = {
            "id": doc['id'],
            "title": doc['title'],
            "source": doc['source'],
            "author": doc['author'],
            "date": doc['date'],
            "content": doc['content'],
            # Chroma 메타데이터는 리스트를 못 담아서 콤마로 join, 조회 시 다시 split
            "tags": ",".join(doc.get('tags', [])),
            "sourceUrl": doc.get('sourceUrl', '')
        }

        docs.append(Document(page_content=page_content, metadata=metadata))

    ids = [doc["id"] for doc in source_docs]
    vectorstore = get_vectorstore()
    # add_documents에 ids를 안 넘기면 매번 랜덤 id로 새로 쌓이기만 해서 재적재할 때마다 중복이
    # 누적된다 — 같은 id를 미리 지운 뒤 넣어서 upsert처럼 동작하게 한다.
    try:
        vectorstore._collection.delete(ids=ids)
    except Exception:
        pass  # 컬렉션이 비어있거나 해당 id가 아직 없으면 조용히 무시
    vectorstore.add_documents(docs, ids=ids)
    print(f"총 {len(docs)}개의 문서가 성공적으로 적재되었습니다.")


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

# 3. LLM 요약 프롬프트 셋업
# 출력 형식을 명확히 지정하기 위해 Pydantic 모델을 활용한 JSON 파서 세팅
parser = JsonOutputParser(pydantic_object=Summary)

prompt_template = """
당신은 사내 지식 관리 AI 어시스턴트입니다. 
사용자의 질문에 답하기 위해, 아래 제공된 검색된 문서(Context)들을 분석하고 요약하세요.

[사용자 질문]
{query}

[검색된 문서들 (Context)]
{context}

[지시사항]
위 문서들을 바탕으로 다음 정보를 추출하여 반드시 JSON 형식으로 응답하세요.
1. keyPoints: 전체 문서의 핵심 내용을 3-4개의 문장으로 요약한 리스트
2. decisionTrail: 시간 순서대로 의사결정의 흐름을 나타내는 리스트. (date, decision, source 포함)
3. actionItems: 문맥상 아직 완료되지 않았거나 진행 중인 할 일 리스트. (id, task, assignee, dueDate, status, source 포함)
   task는 "~한 영역과 ~을 구분" 같은 문서 요약 명사구가 아니라, 실제로 할 일을 지시하는 간결한
   명령형 문장으로 쓰세요 (예: "API 응답 속도 테스트하기", "디자인 시안 최종 검토받기"). 15단어를
   넘지 않게 하고, 누가 봐도 바로 무엇을 해야 하는지 알 수 있어야 합니다.
   status 값은 반드시 "pending", "in-progress", "completed" 셋 중 하나의 영문 문자열이어야 합니다
   (한국어로 쓰지 마세요 — 우리 시스템이 이 값으로 상태를 순환시킵니다).
   decisionTrail과 actionItems의 source 값은 반드시 그 근거가 된 문서의 "문서 출처: " 뒤에 적힌
   값(예: notion, slack, gdrive, github, gitlab)을 그대로 사용하세요. 문서 제목이나 다른 설명을
   적지 마세요.

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

def generate_ai_summary(query: str, retrieved_docs: List[Document], api_key: str = None) -> dict:
    """검색된 문서들을 바탕으로 LLM을 호출하여 요약 JSON을 반환합니다."""
    
    # 1. API 키 확인 (없으면 Dummy 데이터 반환)
    actual_api_key = api_key or os.getenv("OPENAI_API_KEY")
    if not actual_api_key or actual_api_key == "your_openai_api_key_here":
        print("⚠️ OPENAI_API_KEY가 설정되지 않았습니다. Mock 요약을 반환합니다.")
        from dummy_data import mock_summary
        return mock_summary

    try:
        # 2. Context 구성
        context_str = "\n\n---\n\n".join(
            [f"문서 출처: {doc.metadata.get('source', 'unknown')}\n{doc.page_content}" for doc in retrieved_docs]
        )

        # 3. LLM 호출
        llm = ChatOpenAI(temperature=0, model="gpt-4o", openai_api_key=actual_api_key)
        prompt = PromptTemplate(
            template=prompt_template,
            input_variables=["query", "context"],
            partial_variables={"format_instructions": parser.get_format_instructions()},
        )

        chain = prompt | llm | parser
        
        print(f"🤖 LLM 호출 중... (검색된 문서 {len(retrieved_docs)}개 기반)")
        result = chain.invoke({"query": query, "context": context_str})
        
        # Pydantic 모델에 맞는지 확인 (안 맞으면 에러 발생)
        validated_summary = Summary(**result)
        summary_dict = validated_summary.model_dump()
        for item in summary_dict.get("actionItems", []):
            item["status"] = _normalize_status(item.get("status", "pending"))
        return summary_dict
        
    except Exception as e:
        print(f"❌ LLM 호출 중 에러 발생: {e}")
        from dummy_data import mock_summary
        return mock_summary

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
