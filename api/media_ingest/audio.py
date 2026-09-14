"""오디오 추출 코어.

yt-dlp로 최적 오디오 스트림을 무손실 다운로드한 뒤, ffmpeg 후처리로 지정
비트레이트(기본 MP3 192k)로 변환한다.
"""

from __future__ import annotations

import os
from typing import Any

from .base import BaseMediaHandler, MediaRequest, register_handler


@register_handler
class AudioProcessor(BaseMediaHandler):
    """웹 미디어 URL → 오디오 파일(MP3 등) 변환 핸들러."""

    media_type = "audio"

    def __init__(self, *, codec: str = "mp3", bitrate: str = "192", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.codec = codec
        self.bitrate = str(bitrate)

    def build_ydl_options(self, request: MediaRequest) -> dict[str, Any]:
        # bestaudio: 원본에서 가장 좋은 오디오 스트림을 무손실로 확보한 뒤 변환
        return {
            "format": "bestaudio/best",
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": self.codec,
                    "preferredquality": self.bitrate,
                }
            ],
        }

    def build_metadata(self, info: dict[str, Any]) -> dict[str, Any]:
        meta = super().build_metadata(info)
        meta.update({"codec": self.codec, "bitrate_kbps": self.bitrate})
        return meta

    def _resolve_output_path(self, ydl, info: dict[str, Any]) -> str:
        # 후처리(FFmpegExtractAudio)로 확장자가 코덱에 맞게 바뀐다.
        downloads = info.get("requested_downloads")
        if downloads and downloads[0].get("filepath"):
            return downloads[0]["filepath"]
        base, _ = os.path.splitext(ydl.prepare_filename(info))
        return f"{base}.{self.codec}"
