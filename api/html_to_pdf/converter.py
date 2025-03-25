import httpx
import pdfkit
import logging
import shutil
from fastapi import Request

# 로그 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class HTMLToPDFConverter:
    def __init__(self):
        """기본적으로 pdfkit(wkhtmltopdf) 사용"""
        self.wkhtmltopdf_path = shutil.which("wkhtmltopdf")
        if not self.wkhtmltopdf_path:
            raise RuntimeError("wkhtmltopdf 실행 파일을 찾을 수 없습니다. 컨테이너에 설치되어 있는지 확인하세요.")

    async def convert_from_url(self, request: Request, url: str, output_path: str):
        """URL에서 HTML을 가져와 PDF로 변환"""
        headers = {
            "User-Agent": request.headers.get("User-Agent", "Mozilla/5.0"),
            "Accept-Language": request.headers.get("Accept-Language", "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7"),
        }
        logger.info(f"Fetching URL: {url} with User-Agent: {headers['User-Agent']}")

        async with httpx.AsyncClient(headers=headers) as client:
            response = await client.get(url, timeout=10)

        if response.status_code != 200:
            logger.error(f"Failed to fetch URL: {url}, Status Code: {response.status_code}")
            raise ValueError(f"Failed to fetch URL: {url}, Status Code: {response.status_code}")

        # 🔹 HTML 응답이 정상적인지 확인 (첫 500자 출력)
        html_content = response.text
        logger.info(f"Fetched HTML Content Preview (First 500 chars): {html_content[:500]}")

        self.convert(html_content, output_path)

    def convert(self, html_content: str, output_path: str, options: dict = None):
        """HTML을 PDF로 변환"""
        logger.info("Using pdfkit (wkhtmltopdf) for PDF conversion")

        # 🔹 HTML이 한글을 포함하는지 로그 출력
        logger.info(f"HTML Content Preview (First 500 chars): {html_content[:500]}")

        self._convert_with_pdfkit(html_content, output_path, options)

    def _convert_with_pdfkit(self, html_content: str, output_path: str, options: dict = None):
        """pdfkit(wkhtmltopdf)로 PDF 변환"""
        logger.info("Generating PDF with pdfkit (wkhtmltopdf): {html_content}")
        if options is None:
            options = {
                "encoding": "UTF-8",
                "no-outline": None,
                "disable-smart-shrinking": None,
                "user-style-sheet": "/app/fonts.css"  # 한글 폰트 적용
            }

        # 한글 폰트 적용 CSS
        font_css = """
        body {
            font-family: 'Nanum Gothic', 'Noto Sans CJK KR', sans-serif;
        }
        """

        # 폰트 설정 파일 저장
        with open("/app/fonts.css", "w") as f:
            f.write(font_css)

        pdfkit_config = pdfkit.configuration(wkhtmltopdf=self.wkhtmltopdf_path)
        pdfkit.from_string(html_content, output_path, options=options, configuration=pdfkit_config)
