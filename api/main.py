from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api.html_to_pdf.routes import router as pdf_router

app = FastAPI()

# CORS 설정 (필요하면 특정 도메인만 허용 가능)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# HTML → PDF 변환 API 등록
app.include_router(pdf_router, prefix="/api")

@app.get("/")
async def root():
    return {"message": "Q-Utils API is running"}
