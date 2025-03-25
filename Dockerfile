FROM python:3.10

# 필수 패키지 및 한글 폰트 설치
RUN apt-get update && apt-get install -y \
    wkhtmltopdf \
    fonts-nanum \
    fonts-noto-cjk \
    fontconfig \
    && rm -rf /var/lib/apt/lists/*

# 폰트 캐시 갱신 (설치된 폰트를 시스템에서 인식하도록)
RUN fc-cache -fv

# 프로젝트 파일 복사
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . app/
WORKDIR /app
# wkhtmltopdf 실행 파일을 pdfkit에서 찾을 수 있도록 설정

ENV PATH="/usr/local/bin:$PATH"

EXPOSE 8000
CMD ["uvicorn", "web.app:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
