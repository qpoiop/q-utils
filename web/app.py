import logging
import os
from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates
from fastapi.responses import FileResponse
import tempfile
from api.html_to_pdf.converter import HTMLToPDFConverter

logging.basicConfig(level=logging.INFO)  # 로그 설정
logger = logging.getLogger(__name__)

app = FastAPI()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")

templates = Jinja2Templates(directory=TEMPLATES_DIR)
converter = HTMLToPDFConverter()

@app.get("/")
async def home(request: Request):
    logger.info("홈 페이지 요청 받음")
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/convert")
async def convert_to_pdf(request: Request):
    logger.info("HTML 변환 요청 받음")
    data = await request.json()
    html_content = data.get("html", "")

    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp_pdf:
        converter.convert(html_content, temp_pdf.name)
        return FileResponse(temp_pdf.name, filename="output.pdf", media_type="application/pdf")

@app.post("/convert_url")
async def convert_url_to_pdf(request: Request):
    logger.info("URL 변환 요청 받음")
    data = await request.json()
    url = data.get("url", "")

    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp_pdf:
        await converter.convert_from_url(request, url, temp_pdf.name)
        return FileResponse(temp_pdf.name, filename="webpage.pdf", media_type="application/pdf")

