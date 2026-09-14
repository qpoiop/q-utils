"""MediaIngestPipeline — media_type 기반으로 핸들러를 디스패치하는 조립기.

핸들러 인스턴스를 등록해두고 `process(media_type, request)`로 호출한다.
향후 영상/플랫폼 어댑터가 추가되면 `register()`만 하면 파이프라인에 편입된다.
"""

from __future__ import annotations

from typing import Any

from .audio import AudioProcessor  # noqa: F401  (레지스트리 등록 트리거)
from .video import VideoProcessor  # noqa: F401  (레지스트리 등록 트리거)
from .base import (
    HANDLER_REGISTRY,
    BaseMediaHandler,
    MediaProcessingError,
    MediaRequest,
    MediaResult,
)


class MediaIngestPipeline:
    """등록된 핸들러들을 media_type으로 실행하는 파이프라인."""

    def __init__(self) -> None:
        self._handlers: dict[str, BaseMediaHandler] = {}

    def register(self, handler: BaseMediaHandler, media_type: str | None = None) -> BaseMediaHandler:
        """핸들러 인스턴스를 등록."""
        self._handlers[media_type or handler.media_type] = handler
        return handler

    def register_type(self, media_type: str, **kwargs: Any) -> BaseMediaHandler:
        """레지스트리에 등록된 클래스명(media_type)으로 인스턴스를 생성·등록."""
        try:
            cls = HANDLER_REGISTRY[media_type]
        except KeyError as exc:
            raise MediaProcessingError(f"알 수 없는 media_type: {media_type!r}") from exc
        return self.register(cls(**kwargs))

    def get(self, media_type: str) -> BaseMediaHandler:
        try:
            return self._handlers[media_type]
        except KeyError as exc:
            raise MediaProcessingError(
                f"등록되지 않은 media_type: {media_type!r} (사용 가능: {self.media_types})"
            ) from exc

    def process(self, media_type: str, request: MediaRequest) -> MediaResult:
        return self.get(media_type).process(request)

    @property
    def media_types(self) -> list[str]:
        return list(self._handlers)


def build_default_pipeline() -> MediaIngestPipeline:
    """기본 파이프라인(오디오 핸들러 등록)을 구성해 반환."""
    pipeline = MediaIngestPipeline()
    pipeline.register(AudioProcessor())
    pipeline.register(VideoProcessor())
    return pipeline
