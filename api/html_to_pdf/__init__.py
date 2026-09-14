"""HTML/URL → PDF 변환 기능 모듈."""

from api.registry import Feature

from .routes import router

FEATURE = Feature(
    name="html_to_pdf",
    router=router,
    description="HTML/URL → PDF 변환",
)

__all__ = ["FEATURE", "router"]
