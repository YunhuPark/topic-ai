"""서비스 계정(또는 계정 연동한 사용자 본인)에 공유된 Google Drive 파일을 읽어와
Topic Thread AI의 공통 문서 포맷(dict)으로 변환한다. 쓰기 작업은 하지 않는다.

지원 파일 형식 (PRD.md FR-5/Phase 7 참고):
- Google 네이티브: Docs, Sheets, Slides
- 업로드된 원본 파일: PDF, MS Word(.docx), MS Excel(.xlsx), MS PowerPoint(.pptx), 한글 HWPX(.hwpx)

미지원(알려진 한계):
- 스캔 이미지로만 이뤄진 PDF: 텍스트 레이어가 없어 본문을 못 뽑음 (OCR은 범위 밖)
- 레거시 바이너리 .hwp(2014년 이전 한글 파일 포맷)와 구버전 MS Office(.doc/.xls/.ppt):
  신뢰할 만한 순수 파이썬 파서가 없어서 건너뛴다 — 회사에서 최신 한글/오피스로 다시 저장하거나
  PDF로 내보내면 검색 대상이 됨

사전 준비 (사용자가 Google Cloud Console에서 직접 해야 하는 것):
1. GCP 프로젝트 생성 후 "Google Drive API"와 "Google Sheets API" 활성화 (Sheets 문서를
   읽으려면 Sheets API도 켜야 한다 — 계정 연동 시 사용자 OAuth 토큰은 이미 Drive 스코프로
   충분하지만, 서비스 계정 경로에서는 이 API 자체가 프로젝트에서 켜져 있어야 함)
2. IAM & 관리자 > 서비스 계정 > 서비스 계정 만들기 (역할 부여 불필요, 그냥 생성)
3. 만든 서비스 계정 > 키 > 새 키 만들기 > JSON 다운로드
4. 다운받은 JSON 파일을 backend/gdrive_service_account.json 으로 저장 (.gitignore에 이미 포함됨)
5. 서비스 계정 상세 페이지에 있는 이메일(xxx@xxx.iam.gserviceaccount.com)을 복사해서,
   검색되길 원하는 Drive 파일/폴더를 "공유"할 때 뷰어(Viewer) 권한으로 추가
"""

import io
import os
import time
import zipfile
import xml.etree.ElementTree as ET
from typing import Optional

from dotenv import load_dotenv
from docx import Document as DocxDocument
from google.oauth2 import service_account
from google.oauth2.credentials import Credentials as UserCredentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload
from openpyxl import load_workbook
from pptx import Presentation
from pypdf import PdfReader

load_dotenv()

# drive.readonly 하나로 Drive API뿐 아니라 Sheets API도 호출 가능하다 (Google이 문서화한
# Sheets API 허용 스코프 목록에 drive.readonly가 포함돼 있음) — 그래서 계정 연동(OAuth) 쪽
# 스코프는 그대로 두고 서비스 계정 쪽에서만 API를 추가로 켜면 된다.
SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
DEFAULT_KEY_FILE = os.path.join(os.path.dirname(__file__), "..", "gdrive_service_account.json")

MIME_DOC = "application/vnd.google-apps.document"
MIME_SHEET = "application/vnd.google-apps.spreadsheet"
MIME_SLIDES = "application/vnd.google-apps.presentation"
MIME_PDF = "application/pdf"
# 업로드된 원본 파일은 mimeType이 앱마다 제각각이거나 불확실해서(특히 한글 HWP는 Drive가
# 붙이는 mimeType이 문서화가 부실함), mimeType 대신 파일명 확장자로 판별한다 — 아래
# _list_shared_files의 "name contains" 절, _extract_content의 확장자 분기 참고.
UPLOADED_EXTENSIONS = (".docx", ".xlsx", ".pptx", ".hwpx", ".hwp")
SUPPORTED_MIME_TYPES = [MIME_DOC, MIME_SHEET, MIME_SLIDES, MIME_PDF]

_KIND_LABELS = {
    MIME_DOC: "doc",
    MIME_SHEET: "sheet",
    MIME_SLIDES: "slides",
    MIME_PDF: "pdf",
}
_EXTENSION_KIND_LABELS = {
    ".docx": "docx",
    ".xlsx": "xlsx",
    ".pptx": "pptx",
    ".hwpx": "hwpx",
}


def _get_drive_service():
    key_file = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", DEFAULT_KEY_FILE)
    if not os.path.exists(key_file):
        raise RuntimeError(
            "Google 서비스 계정 키 파일을 찾을 수 없습니다. "
            f"'{key_file}' 위치에 JSON 키 파일을 두거나 backend/.env의 GOOGLE_SERVICE_ACCOUNT_FILE로 경로를 지정하세요."
        )
    credentials = service_account.Credentials.from_service_account_file(key_file, scopes=SCOPES)
    return build("drive", "v3", credentials=credentials), build("sheets", "v4", credentials=credentials)


def _build_services_for_user(access_token: str):
    credentials = UserCredentials(token=access_token)
    return build("drive", "v3", credentials=credentials), build("sheets", "v4", credentials=credentials)


def _list_shared_files(drive_service) -> list[dict]:
    """서비스 계정(또는 이 사람 본인)에 공유된 파일 중 지원하는 형식만 반환한다
    (Google 네이티브 Docs/Sheets/Slides + PDF는 mimeType으로, 업로드된 원본 파일은
    mimeType이 애매해 파일명 확장자로 걸러낸다 — .hwp도 일단 여기서 걸러서 가져온 뒤
    _extract_content에서 레거시 바이너리인지(.hwp) 최신 zip 기반(.hwpx)인지 다시 나눈다)."""
    files = []
    page_token: Optional[str] = None
    mime_filter = " or ".join(f"mimeType = '{m}'" for m in SUPPORTED_MIME_TYPES)
    name_filter = " or ".join(f"name contains '{ext}'" for ext in UPLOADED_EXTENSIONS)
    query = f"({mime_filter} or {name_filter}) and trashed = false"
    while True:
        response = drive_service.files().list(
            q=query,
            spaces="drive",
            fields="nextPageToken, files(id, name, mimeType, modifiedTime, owners, webViewLink)",
            pageToken=page_token,
            pageSize=100,
        ).execute()
        files.extend(response.get("files", []))
        page_token = response.get("nextPageToken")
        if not page_token:
            break
    return files


def _export_plain_text(drive_service, file_id: str) -> str:
    """Docs/Slides 둘 다 Drive의 text/plain 내보내기를 지원한다 (Slides는 슬라이드 안의
    텍스트 상자 내용을 순서대로 뽑아준다)."""
    content = drive_service.files().export(fileId=file_id, mimeType="text/plain").execute()
    text = content.decode("utf-8", errors="replace") if isinstance(content, bytes) else str(content)
    # Google 내보내기가 앞에 BOM을 붙이고 줄바꿈을 \r\n으로 주는 것을 정리
    return text.lstrip("﻿").replace("\r\n", "\n")


# Sheets API의 기본 할당량은 "사용자당 분당 60건 읽기 요청" — Sheets 문서 하나당 최소 2건
# (탭 목록 조회 + 탭마다 값 조회)이 필요해서, Sheets 문서가 수십 개만 있어도 금방 넘긴다.
# 넘기면 개별 파일 export가 그냥 실패해서 그 문서 내용이 통째로 누락되므로, 요청 사이에
# 최소 간격을 두어 애초에 한도를 안 넘기고, 그래도 429가 나면 잠깐 쉬었다 재시도한다.
_SHEETS_MIN_INTERVAL_SECONDS = 1.1
_last_sheets_api_call_at = 0.0


def _sheets_api_call(request_builder, **kwargs):
    global _last_sheets_api_call_at
    max_attempts = 5
    for attempt in range(max_attempts):
        elapsed = time.monotonic() - _last_sheets_api_call_at
        if elapsed < _SHEETS_MIN_INTERVAL_SECONDS:
            time.sleep(_SHEETS_MIN_INTERVAL_SECONDS - elapsed)
        _last_sheets_api_call_at = time.monotonic()
        try:
            return request_builder(**kwargs).execute()
        except HttpError as e:
            if e.resp.status == 429 and attempt < max_attempts - 1:
                time.sleep(min(2 ** (attempt + 1), 30))
                continue
            raise


def _export_sheet_text(sheets_service, file_id: str) -> str:
    """모든 시트(탭)를 순회하며 셀 값을 탭으로 구분한 텍스트로 뽑는다. Drive의 CSV 내보내기는
    첫 번째 시트만 나오는 한계가 있어서, 시트가 여러 개인 문서(회의록 탭이 따로 있는 경우 등)도
    놓치지 않도록 Sheets API로 시트별 값을 직접 읽는다."""
    meta = _sheets_api_call(
        sheets_service.spreadsheets().get, spreadsheetId=file_id, fields="sheets.properties.title"
    )
    sheet_titles = [s["properties"]["title"] for s in meta.get("sheets", [])]

    sections = []
    for title in sheet_titles:
        # A1 표기법이라 탭 이름에 공백/특수문자가 있으면 따옴표로 감싸야 한다 (안 그러면 400이
        # 나면서 그 스프레드시트 전체가 통째로 건너뛰어진다). 이름 안의 작은따옴표는 두 번 써서 이스케이프.
        quoted_title = "'" + title.replace("'", "''") + "'"
        values = _sheets_api_call(
            sheets_service.spreadsheets().values().get, spreadsheetId=file_id, range=quoted_title
        ).get("values", [])
        if not values:
            continue
        rows_text = "\n".join("\t".join(str(cell) for cell in row) for row in values)
        sections.append(f"[시트: {title}]\n{rows_text}")
    return "\n\n".join(sections)


def _download_binary(drive_service, file_id: str) -> io.BytesIO:
    """업로드된 원본 파일(PDF/DOCX/XLSX/PPTX/HWPX)은 Drive가 변환해주지 않으므로
    바이트 그대로 내려받는다."""
    buf = io.BytesIO()
    request = drive_service.files().get_media(fileId=file_id)
    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    buf.seek(0)
    return buf


def _extract_pdf_text(drive_service, file_id: str) -> str:
    """스캔 이미지로만 된 PDF는 텍스트 레이어가 없어 빈 문자열이 나올 수 있다 (OCR은 범위 밖)."""
    reader = PdfReader(_download_binary(drive_service, file_id))
    pages_text = [page.extract_text() or "" for page in reader.pages]
    return "\n\n".join(t for t in pages_text if t.strip())


def _extract_docx_text(drive_service, file_id: str) -> str:
    doc = DocxDocument(_download_binary(drive_service, file_id))
    lines = [p.text for p in doc.paragraphs if p.text.strip()]
    for table in doc.tables:
        for row in table.rows:
            cells_text = [c.text for c in row.cells if c.text.strip()]
            if cells_text:
                lines.append("\t".join(cells_text))
    return "\n".join(lines)


def _extract_xlsx_text(drive_service, file_id: str) -> str:
    workbook = load_workbook(_download_binary(drive_service, file_id), data_only=True, read_only=True)
    sections = []
    for sheet in workbook.worksheets:
        rows_text = [
            "\t".join(str(cell) for cell in row if cell is not None)
            for row in sheet.iter_rows(values_only=True)
            if any(cell is not None for cell in row)
        ]
        if rows_text:
            sections.append(f"[시트: {sheet.title}]\n" + "\n".join(rows_text))
    return "\n\n".join(sections)


def _extract_pptx_text(drive_service, file_id: str) -> str:
    presentation = Presentation(_download_binary(drive_service, file_id))
    sections = []
    for i, slide in enumerate(presentation.slides, start=1):
        texts = [
            shape.text_frame.text
            for shape in slide.shapes
            if shape.has_text_frame and shape.text_frame.text.strip()
        ]
        if texts:
            sections.append(f"[슬라이드 {i}]\n" + "\n".join(texts))
    return "\n\n".join(sections)


def _extract_hwpx_text(drive_service, file_id: str) -> str:
    """HWPX(2014년 이후 한글의 zip+XML 기반 포맷)는 Contents/section*.xml 안에 문단이
    <hp:p>/<hp:t> 같은 태그로 들어있다. 네임스페이스 접두사와 무관하게 로컬 태그명이
    't'인 요소의 텍스트만 순서대로 이어붙인다."""
    buf = _download_binary(drive_service, file_id)
    lines = []
    with zipfile.ZipFile(buf) as z:
        section_names = sorted(
            n for n in z.namelist() if n.startswith("Contents/section") and n.endswith(".xml")
        )
        for name in section_names:
            root = ET.fromstring(z.read(name))
            for elem in root.iter():
                tag = elem.tag.split("}")[-1]
                if tag == "t" and elem.text:
                    lines.append(elem.text)
    return "\n".join(lines)


def _extract_content(drive_service, sheets_service, f: dict) -> Optional[str]:
    """None을 반환하면 지원하지 않는 형식이라는 뜻으로, 호출 쪽에서 이 파일 자체를 건너뛴다
    (빈 문자열 ""은 "지원은 하지만 이 문서엔 텍스트가 없었다"는 뜻이라 구분한다)."""
    mime = f.get("mimeType")
    name = (f.get("name") or "").lower()

    if mime in (MIME_DOC, MIME_SLIDES):
        return _export_plain_text(drive_service, f["id"])
    if mime == MIME_SHEET:
        return _export_sheet_text(sheets_service, f["id"])
    if mime == MIME_PDF:
        return _extract_pdf_text(drive_service, f["id"])
    if name.endswith(".docx"):
        return _extract_docx_text(drive_service, f["id"])
    if name.endswith(".xlsx"):
        return _extract_xlsx_text(drive_service, f["id"])
    if name.endswith(".pptx"):
        return _extract_pptx_text(drive_service, f["id"])
    if name.endswith(".hwpx"):
        return _extract_hwpx_text(drive_service, f["id"])
    if name.endswith(".hwp"):
        # 레거시 바이너리 .hwp는 신뢰할 만한 순수 파이썬 파서가 없어 건너뛴다
        # (모듈 docstring의 "미지원" 항목 참고).
        return None
    return None


def _resolve_kind(f: dict) -> Optional[str]:
    mime = f.get("mimeType")
    if mime in _KIND_LABELS:
        return _KIND_LABELS[mime]
    name = (f.get("name") or "").lower()
    for ext, kind in _EXTENSION_KIND_LABELS.items():
        if name.endswith(ext):
            return kind
    return None


def _convert_files(
    drive_service, sheets_service, files: list[dict], known: Optional[dict[str, str]] = None
) -> tuple[list[dict], set[str]]:
    """(새로 본문을 받아온 문서들, 원본에 현재 존재하는 전체 문서 id) 를 반환한다.

    known({id: 지난번 modifiedTime})을 주면 수정 시각이 그대로인 파일은 **본문을 아예 받지 않는다** —
    PDF/DOCX 원본을 15분마다 통째로 다시 내려받고 Sheets 할당량을 태우던 문제가 여기서 사라진다.
    전체 id 집합은 항상 반환해야 원본에서 삭제된 문서를 정리할 수 있다."""
    known = known or {}
    documents = []
    seen_ids = set()

    for f in files:
        kind = _resolve_kind(f)
        if kind is None:
            print(f"'{f.get('name')}'는 지원하지 않는 파일 형식이라 건너뜁니다 (예: 레거시 .hwp).")
            continue

        doc_id = f"gdrive-{f['id']}"
        seen_ids.add(doc_id)
        modified_at = f.get("modifiedTime") or ""
        if modified_at and known.get(doc_id) == modified_at:
            continue  # 원본이 그대로 → 본문 재수집/재임베딩 불필요

        try:
            content = _extract_content(drive_service, sheets_service, f)
        except Exception as e:
            # HttpError뿐 아니라 손상된 PDF(pypdf), 잘린 hwpx(BadZipFile), XML 파싱 오류 등도
            # 여기서 잡아야 한다 — 예전엔 파일 하나 때문에 그 주기의 Drive 수집 전체가 날아갔다.
            print(f"'{f.get('name')}' 내보내기 실패, 건너뜁니다: {e}")
            continue
        if content is None:
            continue

        owners = f.get("owners") or []
        author = owners[0]["displayName"] if owners else "알 수 없음"
        date = modified_at[:10] or "1970-01-01"

        documents.append({
            "id": doc_id,
            "title": f.get("name") or "제목 없음",
            "source": "gdrive",
            "author": author,
            "authorAvatar": author[:2],
            "date": date,
            "content": content if content.strip() else "(본문 없음)",
            "tags": ["gdrive", kind],
            "freshness": "fresh",
            "relevance": 1.0,
            "sourceUrl": f.get("webViewLink", ""),
            "sourceUpdatedAt": modified_at,
        })
    return documents, seen_ids


def fetch_gdrive_documents() -> list[dict]:
    """서비스 계정에 공유된 모든 지원 파일을 공통 문서 포맷으로 변환해 반환한다 (관리자 일괄 적재용)."""
    drive_service, sheets_service = _get_drive_service()
    try:
        files = _list_shared_files(drive_service)
    except HttpError as e:
        raise RuntimeError(f"Google Drive API 호출 실패: {e}") from e
    documents, _ = _convert_files(drive_service, sheets_service, files)
    return documents


def fetch_gdrive_documents_for_user(
    access_token: str, known: Optional[dict[str, str]] = None
) -> tuple[list[dict], set[str]]:
    """계정 연동으로 받은 이 사람 본인의 Drive OAuth access token으로, 이 사람 소유이거나
    공유받은 지원 파일 전체를 가져온다. 서비스 계정에 파일을 일일이 공유해야 하는
    fetch_gdrive_documents()와 달리 별도 공유 작업이 필요 없다.

    known({id: 지난번 modifiedTime})을 주면 바뀐 파일만 본문을 받아온다."""
    drive_service, sheets_service = _build_services_for_user(access_token)
    try:
        files = _list_shared_files(drive_service)
    except HttpError as e:
        raise RuntimeError(f"Google Drive API 호출 실패: {e}") from e
    return _convert_files(drive_service, sheets_service, files, known)


if __name__ == "__main__":
    docs = fetch_gdrive_documents()
    print(f"공유된 Drive 파일 {len(docs)}개를 가져왔습니다.")
    for d in docs:
        print(f" - [{d['id']}] {d['title']} ({d['author']}, {d['date']})")
