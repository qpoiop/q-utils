from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.registry import available_modules, register_features

app = FastAPI(title="q-utils API")

# CORS 설정 (필요하면 특정 도메인만 허용 가능)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 활성 기능 모듈을 /api 접두사로 선택적 등록
ENABLED_MODULES = register_features(app, prefix="/api")


@app.get("/")
async def root():
    return {
        "message": "Q-Utils API is running",
        "modules": {"enabled": ENABLED_MODULES, "available": available_modules()},
    }
