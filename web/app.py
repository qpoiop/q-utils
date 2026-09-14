import logging
import os

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from api.registry import available_modules, register_features

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")

app = FastAPI(title="q-utils")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


@app.get("/")
async def home(request: Request):
    logger.info("홈 페이지 요청 받음")
    return templates.TemplateResponse(
        "index.html", {"request": request, "modules": ENABLED_MODULES}
    )


@app.get("/modules")
async def modules():
    """활성/전체 모듈 상태."""
    return {"enabled": ENABLED_MODULES, "available": available_modules()}


# 활성 기능 모듈을 선택적으로 등록 (하드코딩된 include_router 대신 레지스트리 기반)
# 웹 UI는 접두사 없이 각 모듈의 경로를 그대로 노출 (예: /convert, /media/*)
ENABLED_MODULES = register_features(app, prefix="")
