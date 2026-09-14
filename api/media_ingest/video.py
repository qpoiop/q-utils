"""비디오 컨테이너 처리 모듈.

최고 화질 비디오 스트림과 오디오 스트림을 각각 받아 ffmpeg로 단일 MP4
컨테이너로 합성(muxing)한다. 원본 해상도를 유지하며, 재인코딩 없이
스트림을 그대로 병합한다.
"""

from __future__ import annotations

import os
from typing import Any, Optional

from .base import BaseMediaHandler, MediaRequest, register_handler


@register_handler
class VideoProcessor(BaseMediaHandler):
    """웹 미디어 URL → 단일 컨테이너(MP4) 비디오 핸들러."""

    media_type = "video"

    # 원본 화질 유지 + 무손실 병합(비디오/오디오 스트림을 재인코딩 없이 mux)
    DEFAULT_FORMAT = "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best"

    def __init__(
        self,
        *,
        container: str = "mp4",
        format_spec: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.container = container
        self.format_spec = format_spec or self.DEFAULT_FORMAT

    def build_ydl_options(self, request: MediaRequest) -> dict[str, Any]:
        return {
            "format": self.format_spec,
            # 분리된 video/audio 스트림을 단일 컨테이너로 muxing
            "merge_output_format": self.container,
        }

    def build_metadata(self, info: dict[str, Any]) -> dict[str, Any]:
        meta = super().build_metadata(info)
        width = info.get("width")
        height = info.get("height")
        meta.update(
            {
                "container": self.container,
                "width": width,
                "height": height,
                "resolution": (
                    f"{width}x{height}" if width and height else info.get("resolution")
                ),
                "fps": info.get("fps"),
                "vcodec": info.get("vcodec"),
                "acodec": info.get("acodec"),
            }
        )
        return meta

    def _resolve_output_path(self, ydl, info: dict[str, Any]) -> str:
        # merge 후 최종 컨테이너 확장자로 파일명이 확정된다.
        downloads = info.get("requested_downloads")
        if downloads and downloads[0].get("filepath"):
            return downloads[0]["filepath"]
        base, _ = os.path.splitext(ydl.prepare_filename(info))
        return f"{base}.{self.container}"
