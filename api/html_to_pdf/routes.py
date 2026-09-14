from __future__ import annotations

import os
import tempfile

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from .converter import HTMLToPDFConverter

router = APIRouter()

# 지연 초기화: 모듈 import 시점에 wkhtmltopdf를 요구하지 않는다(선택적 로딩/테스트 용이).
_converter: HTMLToPDFConverter | None = None


def _get_converter() -> HTMLToPDFConverter:
    global _converter
    if _converter is None:
        _converter = HTMLToPDFConverter()
    return _converter


def _pdf_response(temp_path: str, filename: str) -> FileResponse:
    """PDF 파일 응답 + 전송 후 임시 파일 삭제."""
    return FileResponse(
        temp_path,
        filename=filename,
        media_type="application/pdf",
        background=BackgroundTask(os.remove, temp_path),
    )


@router.post("/convert")
@router.post("/html_to_pdf")
async def convert_to_pdf(request: Request):
    """HTML을 PDF로 변환하는 API."""
    data = await request.json()
    html_content = data.get("html", "")
    if not html_content.strip():
        raise HTTPException(status_code=400, detail="HTML 내용이 필요합니다.")

    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp_pdf:
        temp_path = temp_pdf.name
    _get_converter().convert(html_content, temp_path)
    return _pdf_response(temp_path, "output.pdf")


@router.post("/convert_url")
@router.post("/url_to_pdf")
async def convert_url_to_pdf(request: Request):
    """URL을 입력받아 웹페이지를 PDF로 변환하는 API."""
    data = await request.json()
    url = data.get("url", "")
    if not url.strip():
        raise HTTPException(status_code=400, detail="URL이 필요합니다.")

    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp_pdf:
        temp_path = temp_pdf.name
    try:
        await _get_converter().convert_from_url(request, url, temp_path)
    except ValueError as exc:
        os.remove(temp_path)
        raise HTTPException(status_code=400, detail=str(exc))
    return _pdf_response(temp_path, "webpage.pdf")
