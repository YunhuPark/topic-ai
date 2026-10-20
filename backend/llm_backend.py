"""
LLM/임베딩 백엔드 추상화 계층.

기업 보안 정책상 문서 내용을 외부 API(OpenAI 등)로 절대 보낼 수 없는 환경(금융/공공기관처럼
데이터가 회사망 밖으로 나가면 안 되는 경우)을 대비해, 요약 생성과 임베딩 생성을 백엔드
전환 가능하게 분리해뒀다. 검색/RAG 파이프라인(rag_pipeline.py)의 비즈니스 로직은 이 모듈
뒤에 어떤 백엔드가 있는지 몰라도 되고, LLM_BACKEND 환경변수 하나로 전환한다 — 코드 변경 없이
.env 설정만 바꾸면 된다.

- openai (기본값): OpenAI 호스티드 API. 지금까지 쓰던 방식, 별도 인프라 없이 가장 빠르게
  쓸 수 있지만 문서 내용이 외부 API로 전송된다.
- ollama: 회사 내부망(또는 로컬 PC)에 띄운 Ollama 서버를 그대로 가리킨다. 모델을 자체
  호스팅하므로 문서 내용이 외부로 전혀 나가지 않는다 — 보안 정책상 상용 LLM을 못 쓰는
  회사에서 이 프로젝트를 그대로 쓸 수 있는지에 대한 현실적인 답이다. 대신 응답 품질/속도는
  호스팅한 서버 사양과 고른 오픈 웨이트 모델에 좌우된다.
"""
import json
import os
from typing import List

import requests

LLM_BACKEND = os.getenv("LLM_BACKEND", "openai").strip().lower()

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
# 채팅/임베딩 각각 이 용도에 맞게 널리 쓰이는 기본 모델 — 회사 내부망에 이미 다른 모델을
# 받아뒀다면 .env에서 그대로 덮어쓰면 된다.
OLLAMA_CHAT_MODEL = os.getenv("OLLAMA_CHAT_MODEL", "llama3.1")
OLLAMA_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")
# 로컬 LLM은 호스팅 사양에 따라 OpenAI보다 한 응답에 훨씬 오래 걸릴 수 있어(특히 CPU만
# 있는 서버) 타임아웃을 OpenAI(60초)보다 넉넉히 잡는다.
OLLAMA_TIMEOUT_SECONDS = int(os.getenv("OLLAMA_TIMEOUT_SECONDS", "180"))


def is_ollama_backend() -> bool:
    return LLM_BACKEND == "ollama"


def ollama_embed_texts(texts: List[str]) -> List[List[float]]:
    """Ollama의 /api/embeddings를 호출한다. OpenAI 임베딩 API와 달리 텍스트 하나당 한 번씩
    호출하는 구조라(배치 엔드포인트가 없음) 문서 수가 많으면 OpenAI 배치 호출보다 느리다 —
    사내 대량 색인 시나리오에서는 이게 실제 체감 속도 차이로 나타날 수 있다는 걸 감안해야 한다."""
    vectors: List[List[float]] = []
    for text in texts:
        resp = requests.post(
            f"{OLLAMA_BASE_URL}/api/embeddings",
            json={"model": OLLAMA_EMBED_MODEL, "prompt": text},
            timeout=OLLAMA_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        vectors.append(resp.json()["embedding"])
    return vectors


def ollama_chat_json(prompt: str) -> dict:
    """Ollama의 채팅 API를 JSON 강제 출력 모드(format="json")로 호출한다 — OpenAI의
    response_format={"type": "json_object"}와 같은 역할이라, 호출부(rag_pipeline.py)는
    "JSON 문자열을 파싱한 dict를 받는다"는 계약만 알면 되고 어느 백엔드인지 몰라도 된다."""
    resp = requests.post(
        f"{OLLAMA_BASE_URL}/api/chat",
        json={
            "model": OLLAMA_CHAT_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "format": "json",
            "stream": False,
            "options": {"temperature": 0},
        },
        timeout=OLLAMA_TIMEOUT_SECONDS,
    )
    resp.raise_for_status()
    content = resp.json()["message"]["content"]
    return json.loads(content)


def ollama_health_check() -> tuple[bool, str]:
    """Ollama 서버가 떠 있고 필요한 두 모델(채팅/임베딩)이 실제로 받아져 있는지 확인한다.
    설정 실수(Ollama 미설치, 모델 미다운로드)를 검색 요청이 들어올 때야 500으로 처음 알게
    되는 대신, 서버 기동 시점에 바로 안내하기 위함(main.py 시작 시 한 번 호출)."""
    try:
        resp = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=5)
        resp.raise_for_status()
    except Exception as e:
        return False, f"Ollama 서버({OLLAMA_BASE_URL})에 연결할 수 없습니다: {e}"

    installed = {m.get("name", "").split(":")[0] for m in resp.json().get("models", [])}
    missing = [m for m in (OLLAMA_CHAT_MODEL, OLLAMA_EMBED_MODEL) if m.split(":")[0] not in installed]
    if missing:
        return False, (
            f"Ollama에 다음 모델이 없습니다: {', '.join(missing)} "
            f"(터미널에서 'ollama pull {missing[0]}' 등으로 받으세요)"
        )
    return True, "ok"
