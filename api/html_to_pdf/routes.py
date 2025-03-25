from fastapi import APIRouter, Request
from fastapi.responses import FileResponse
import tempfile
from .converter import HTMLToPDFConverter

router = APIRouter()
converter = HTMLToPDFConverter()

@router.post("/html_to_pdf")
async def convert_to_pdf(request: Request):
    """HTML을 PDF로 변환하는 API"""
    data = await request.json()
    html_content = data.get("html", "")

    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp_pdf:
        converter.convert(html_content, temp_pdf.name)
        return FileResponse(temp_pdf.name, filename="output.pdf", media_type="application/pdf")

@router.post("/url_to_pdf")
async def convert_url_to_pdf(request: Request):
    """URL을 입력받아 웹페이지를 PDF로 변환하는 API"""
    data = await request.json()
    url = data.get("url")

    if not url:
        return {"error": "URL is required"}

    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp_pdf:
        await converter.convert_from_url(request, url, temp_pdf.name)  # request 객체 전달
        return FileResponse(temp_pdf.name, filename="webpage.pdf", media_type="application/pdf")
