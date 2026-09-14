import ipaddress
import logging
import os
import shutil
import socket
from urllib.parse import urlsplit

import httpx
import pdfkit
from fastapi import Request

# 로그 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 프로젝트 루트 기준으로 폰트 CSS 경로 계산 (컨테이너/로컬 모두 동작)
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FONTS_CSS_PATH = os.path.join(PROJECT_ROOT, "fonts.css")

# 외부 URL fetch 시 허용할 스킴
ALLOWED_SCHEMES = {"http", "https"}


def _assert_public_url(url: str) -> None:
    """SSRF 방어: 스킴 검증 + 사설/루프백/링크로컬 IP 차단."""
    parts = urlsplit(url)
    if parts.scheme not in ALLOWED_SCHEMES:
        raise ValueError(f"허용되지 않은 URL 스킴입니다: {parts.scheme!r}")
    host = parts.hostname
    if not host:
        raise ValueError("URL에 호스트가 없습니다.")

    # 호스트가 가리키는 모든 IP를 검사 (DNS rebinding/내부망 접근 차단)
    try:
        infos = socket.getaddrinfo(host, parts.port or None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise ValueError(f"호스트를 확인할 수 없습니다: {host}") from exc

    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            raise ValueError(f"내부/예약된 주소로의 요청은 허용되지 않습니다: {ip}")


class HTMLToPDFConverter:
    def __init__(self):
        """기본적으로 pdfkit(wkhtmltopdf) 사용"""
        self.wkhtmltopdf_path = shutil.which("wkhtmltopdf")
        if not self.wkhtmltopdf_path:
            raise RuntimeError("wkhtmltopdf 실행 파일을 찾을 수 없습니다. 컨테이너에 설치되어 있는지 확인하세요.")
        self._pdfkit_config = pdfkit.configuration(wkhtmltopdf=self.wkhtmltopdf_path)

    async def convert_from_url(self, request: Request, url: str, output_path: str):
        """URL에서 HTML을 가져와 PDF로 변환"""
        _assert_public_url(url)

        headers = {
            "User-Agent": request.headers.get("User-Agent", "Mozilla/5.0"),
            "Accept-Language": request.headers.get(
                "Accept-Language", "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7"
            ),
        }
        logger.info("Fetching URL: %s", url)

        async with httpx.AsyncClient(headers=headers, follow_redirects=False) as client:
            response = await client.get(url, timeout=10)

        if response.status_code != 200:
            logger.error("Failed to fetch URL: %s, Status Code: %s", url, response.status_code)
            raise ValueError(f"Failed to fetch URL: {url}, Status Code: {response.status_code}")

        self.convert(response.text, output_path)

    def convert(self, html_content: str, output_path: str, options: dict = None):
        """HTML을 PDF로 변환"""
        logger.info("Using pdfkit (wkhtmltopdf) for PDF conversion (%d chars)", len(html_content))

        if options is None:
            options = {
                "encoding": "UTF-8",
                "no-outline": None,
                "disable-smart-shrinking": None,
            }
            # 한글 폰트 CSS가 있으면 적용
            if os.path.exists(FONTS_CSS_PATH):
                options["user-style-sheet"] = FONTS_CSS_PATH

        pdfkit.from_string(
            html_content, output_path, options=options, configuration=self._pdfkit_config
        )
