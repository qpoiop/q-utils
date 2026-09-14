FROM python:3.10-bookworm

# ffmpeg(미디어) · 한글 폰트 · wkhtmltopdf 의존 라이브러리 설치
RUN apt-get update && apt-get install -y \
    ffmpeg \
    fonts-nanum \
    fonts-noto-cjk \
    fontconfig \
    xfonts-75dpi \
    xfonts-base \
    wget \
    && rm -rf /var/lib/apt/lists/*

# wkhtmltopdf: 데비안 저장소에서 제거되어 공식 릴리스 .deb(patched-qt)로 설치
ARG WKHTMLTOPDF_VERSION=0.12.6.1-3
RUN set -eux; \
    arch="$(dpkg --print-architecture)"; \
    wget -O /tmp/wkhtmltox.deb \
      "https://github.com/wkhtmltopdf/packaging/releases/download/${WKHTMLTOPDF_VERSION}/wkhtmltox_${WKHTMLTOPDF_VERSION}.bookworm_${arch}.deb"; \
    apt-get update; \
    apt-get install -y --no-install-recommends /tmp/wkhtmltox.deb; \
    rm -rf /tmp/wkhtmltox.deb /var/lib/apt/lists/*; \
    wkhtmltopdf --version

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
