"""서비스 계정에 공유된 Google Docs를 읽어와 Topic Thread AI의 공통 문서
포맷(dict)으로 변환한다. 쓰기 작업은 하지 않는다. Google Docs만 지원한다
(Sheets/Slides/PDF는 Out of scope — PRD.md FR-5 참고).

사전 준비 (사용자가 Google Cloud Console에서 직접 해야 하는 것):
1. GCP 프로젝트 생성 후 "Google Drive API" 활성화
2. IAM & 관리자 > 서비스 계정 > 서비스 계정 만들기 (역할 부여 불필요, 그냥 생성)
3. 만든 서비스 계정 > 키 > 새 키 만들기 > JSON 다운로드
4. 다운받은 JSON 파일을 backend/gdrive_service_account.json 으로 저장 (.gitignore에 이미 포함됨)
5. 서비스 계정 상세 페이지에 있는 이메일(xxx@xxx.iam.gserviceaccount.com)을 복사해서,
   검색되길 원하는 Google Docs/폴더를 "공유"할 때 뷰어(Viewer) 권한으로 추가
"""

import os
from typing import Optional

from dotenv import load_dotenv
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

load_dotenv()

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
GOOGLE_DOC_MIME_TYPE = "application/vnd.google-apps.document"
DEFAULT_KEY_FILE = os.path.join(os.path.dirname(__file__), "..", "gdrive_service_account.json")


def _get_drive_service():
    key_file = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", DEFAULT_KEY_FILE)
    if not os.path.exists(key_file):
        raise RuntimeError(
            "Google 서비스 계정 키 파일을 찾을 수 없습니다. "
            f"'{key_file}' 위치에 JSON 키 파일을 두거나 backend/.env의 GOOGLE_SERVICE_ACCOUNT_FILE로 경로를 지정하세요."
        )
    credentials = service_account.Credentials.from_service_account_file(key_file, scopes=SCOPES)
    return build("drive", "v3", credentials=credentials)


def _list_shared_google_docs(service) -> list[dict]:
    """서비스 계정에 공유된 파일 중 Google Docs만 반환한다."""
    files = []
    page_token: Optional[str] = None
    query = f"mimeType = '{GOOGLE_DOC_MIME_TYPE}' and trashed = false"
    while True:
        response = service.files().list(
            q=query,
            spaces="drive",
            fields="nextPageToken, files(id, name, modifiedTime, owners, webViewLink)",
            pageToken=page_token,
            pageSize=100,
        ).execute()
        files.extend(response.get("files", []))
        page_token = response.get("nextPageToken")
        if not page_token:
            break
    return files


def _export_doc_text(service, file_id: str) -> str:
    content = service.files().export(fileId=file_id, mimeType="text/plain").execute()
    text = content.decode("utf-8", errors="replace") if isinstance(content, bytes) else str(content)
    # Google 내보내기가 앞에 BOM을 붙이고 줄바꿈을 \r\n으로 주는 것을 정리
    return text.lstrip("﻿").replace("\r\n", "\n")


def fetch_gdrive_documents() -> list[dict]:
    """서비스 계정에 공유된 모든 Google Docs를 공통 문서 포맷으로 변환해 반환한다."""
    service = _get_drive_service()

    documents = []
    try:
        files = _list_shared_google_docs(service)
    except HttpError as e:
        raise RuntimeError(f"Google Drive API 호출 실패: {e}") from e

    for f in files:
        try:
            content = _export_doc_text(service, f["id"])
        except HttpError as e:
            print(f"'{f.get('name')}' 내보내기 실패, 건너뜁니다: {e}")
            continue

        owners = f.get("owners") or []
        author = owners[0]["displayName"] if owners else "알 수 없음"
        date = (f.get("modifiedTime") or "")[:10] or "1970-01-01"

        documents.append({
            "id": f"gdrive-{f['id']}",
            "title": f.get("name") or "제목 없음",
            "source": "gdrive",
            "author": author,
            "authorAvatar": author[:2],
            "date": date,
            "content": content if content.strip() else "(본문 없음)",
            "tags": ["gdrive"],
            "freshness": "fresh",
            "relevance": 1.0,
            "sourceUrl": f.get("webViewLink", ""),
        })
    return documents


if __name__ == "__main__":
    docs = fetch_gdrive_documents()
    print(f"공유된 Google Docs {len(docs)}개를 가져왔습니다.")
    for d in docs:
        print(f" - [{d['id']}] {d['title']} ({d['author']}, {d['date']})")
