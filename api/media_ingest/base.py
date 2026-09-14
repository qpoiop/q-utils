"""미디어 처리 파이프라인의 공통 베이스.

`BaseMediaHandler`는 yt-dlp + ffmpeg 실행, 진행률 로깅, 네트워크 재시도 같은
공통 로직을 템플릿 메서드(`process`)로 제공한다. 오디오/영상/플랫폼별 어댑터는
`build_ydl_options()`(필수)와 몇몇 훅만 재정의하면 손쉽게 붙일 수 있다.
"""

from __future__ import annotations

import logging
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, ClassVar, Optional

logger = logging.getLogger(__name__)


class MediaProcessingError(RuntimeError):
    """미디어 처리 실패(다운로드/변환 등)를 나타내는 예외."""


def _import_yt_dlp():
    """yt-dlp를 지연 임포트한다.

    미설치 환경에서도 나머지 앱이 정상 임포트되도록, 실제 사용 시점에만 로드하고
    없으면 명확한 메시지를 던진다.
    """
    try:
        import yt_dlp  # type: ignore
    except ImportError as exc:  # pragma: no cover - 환경 의존
        raise MediaProcessingError(
            "yt-dlp가 설치되어 있지 않습니다. `pip install yt-dlp` 후 다시 시도하세요."
        ) from exc
    return yt_dlp


def normalize_cookies_from_browser(value: Any) -> Optional[tuple]:
    """cookies-from-browser 설정을 yt-dlp가 기대하는 튜플 형태로 정규화.

    허용 입력: "chrome" | ("chrome",) | ("chrome", "Profile 1", ...)
    yt-dlp 규격: (browser, profile, keyring, container)
    """
    if not value:
        return None
    if isinstance(value, str):
        return (value,)
    if isinstance(value, (tuple, list)):
        return tuple(value)
    raise MediaProcessingError(f"잘못된 cookies_from_browser 값: {value!r}")


@dataclass
class MediaRequest:
    """단일 미디어 처리 요청."""

    url: str
    output_dir: str
    filename_template: str = "%(title)s.%(ext)s"
    # 요청 단위 추가 옵션. {"ydl_options": {...}} 형태로 yt-dlp 옵션을 덮어쓸 수 있다.
    options: dict[str, Any] = field(default_factory=dict)


@dataclass
class MediaResult:
    """처리 결과."""

    media_type: str
    source_url: str
    output_path: str
    title: Optional[str] = None
    duration: Optional[float] = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """오디오/비디오 공통 반환 규격.

        file_path, file_size, duration, resolution 등을 일관된 키로 노출한다.
        """
        return {
            "media_type": self.media_type,
            "source_url": self.source_url,
            "file_path": self.output_path,
            "file_size": self.metadata.get("file_size"),
            "title": self.title,
            "duration": self.duration,
            "resolution": self.metadata.get("resolution"),
            "metadata": self.metadata,
        }


# ---------------------------------------------------------------------------
# 플러그인 레지스트리: media_type -> 핸들러 클래스
# ---------------------------------------------------------------------------
HANDLER_REGISTRY: dict[str, type["BaseMediaHandler"]] = {}


def register_handler(cls: type["BaseMediaHandler"]) -> type["BaseMediaHandler"]:
    """핸들러 클래스를 전역 레지스트리에 등록하는 데코레이터."""
    HANDLER_REGISTRY[cls.media_type] = cls
    return cls


class BaseMediaHandler(ABC):
    """모든 미디어 핸들러의 추상 베이스.

    확장 지점:
      - `media_type`      : 파이프라인 디스패치 키 (필수, 서브클래스에서 지정)
      - `build_ydl_options`: yt-dlp 포맷/후처리 옵션 정의 (필수)
      - `on_progress`     : 진행률 이벤트 커스텀 처리 (선택)
      - `build_metadata`  : 결과 metadata 확장 (선택)
    """

    media_type: ClassVar[str] = "base"

    def __init__(
        self,
        *,
        retries: int = 3,
        backoff_base: float = 2.0,
        backoff_max: float = 10.0,
        quiet: bool = True,
        progress_callback: Optional[Callable[[dict[str, Any]], None]] = None,
        logger_: Optional[logging.Logger] = None,
    ) -> None:
        self.retries = max(1, retries)
        self.backoff_base = backoff_base
        self.backoff_max = backoff_max
        self.quiet = quiet
        # 진행 이벤트 외부 소비자(예: SSE 스트림)에게 전달하는 콜백
        self.progress_callback = progress_callback
        self.logger = logger_ or logging.getLogger(f"{__name__}.{self.media_type}")

    def _emit(self, event: dict[str, Any]) -> None:
        """진행 이벤트를 콜백으로 방출(콜백 예외는 처리 흐름을 막지 않음)."""
        if self.progress_callback is None:
            return
        try:
            self.progress_callback(event)
        except Exception:  # noqa: BLE001 - 모니터링 콜백이 처리를 중단시키지 않도록
            self.logger.debug("progress_callback 예외 무시", exc_info=True)

    # ----- 서브클래스가 반드시 정의 -----
    @abstractmethod
    def build_ydl_options(self, request: MediaRequest) -> dict[str, Any]:
        """이 핸들러 고유의 yt-dlp 옵션(format, postprocessors 등)을 반환."""
        raise NotImplementedError

    # ----- 선택적 확장 훅 -----
    def on_progress(self, event: dict[str, Any]) -> None:
        """진행률 이벤트 훅. 서브클래스/외부에서 재정의 가능."""

    def build_metadata(self, info: dict[str, Any]) -> dict[str, Any]:
        """결과 metadata를 확장. 기본은 자주 쓰는 필드 일부만 추출."""
        return {
            "id": info.get("id"),
            "extractor": info.get("extractor"),
            "ext": info.get("ext"),
            "uploader": info.get("uploader"),
        }

    # ----- 공통 로직 -----
    def _progress_hook(self, d: dict[str, Any]) -> None:
        status = d.get("status")
        if status == "downloading":
            pct = (d.get("_percent_str") or "").strip()
            speed = (d.get("_speed_str") or "").strip()
            eta = (d.get("_eta_str") or "").strip()
            self.logger.info("[%s] 다운로드 %s speed=%s eta=%s", self.media_type, pct, speed, eta)
        elif status == "finished":
            self.logger.info("[%s] 다운로드 완료, 후처리 시작: %s", self.media_type, d.get("filename"))
        elif status == "error":
            self.logger.error("[%s] 다운로드 오류: %s", self.media_type, d.get("filename"))
        self.on_progress(d)
        self._emit(
            {
                "phase": "download",
                "status": status,
                "percent": (d.get("_percent_str") or "").strip(),
                "speed": (d.get("_speed_str") or "").strip(),
                "eta": (d.get("_eta_str") or "").strip(),
                "downloaded_bytes": d.get("downloaded_bytes"),
                "total_bytes": d.get("total_bytes") or d.get("total_bytes_estimate"),
            }
        )

    def _postprocessor_hook(self, d: dict[str, Any]) -> None:
        self.logger.info(
            "[%s] 후처리 %s: %s", self.media_type, d.get("status"), d.get("postprocessor")
        )
        self._emit(
            {
                "phase": "postprocess",
                "status": d.get("status"),
                "postprocessor": d.get("postprocessor"),
            }
        )

    def _base_options(self, request: MediaRequest) -> dict[str, Any]:
        """모든 핸들러가 공유하는 기본 yt-dlp 옵션."""
        outtmpl = os.path.join(request.output_dir, request.filename_template)
        opts: dict[str, Any] = {
            "outtmpl": outtmpl,
            "quiet": self.quiet,
            "no_warnings": self.quiet,
            "noprogress": True,  # 콘솔 프로그레스바 대신 progress_hooks 사용
            "restrictfilenames": True,
            "retries": self.retries,          # yt-dlp 내부 조각 재시도
            "fragment_retries": self.retries,
            "progress_hooks": [self._progress_hook],
            "postprocessor_hooks": [self._postprocessor_hook],
        }
        # 플랫폼 정책 대응 옵션(브라우저 세션 쿠키 / 요청 간 지연)을 1급으로 통과
        cookies = normalize_cookies_from_browser(request.options.get("cookies_from_browser"))
        if cookies:
            opts["cookiesfrombrowser"] = cookies
        if request.options.get("sleep_interval") is not None:
            opts["sleep_interval"] = request.options["sleep_interval"]
        if request.options.get("max_sleep_interval") is not None:
            opts["max_sleep_interval"] = request.options["max_sleep_interval"]
        return opts

    def _compose_options(self, request: MediaRequest) -> dict[str, Any]:
        options = self._base_options(request)
        options.update(self.build_ydl_options(request))
        # 요청 단위 오버라이드(최우선)
        override = request.options.get("ydl_options")
        if isinstance(override, dict):
            options.update(override)
        return options

    @staticmethod
    def _resolve_output_path(ydl, info: dict[str, Any]) -> str:
        """후처리까지 반영된 최종 결과 파일 경로를 최대한 정확히 계산."""
        downloads = info.get("requested_downloads")
        if downloads and downloads[0].get("filepath"):
            return downloads[0]["filepath"]
        # 폴백: 후처리(오디오 변환) 후 확장자가 바뀌는 경우 대응은 서브클래스 책임
        return ydl.prepare_filename(info)

    def _build_result(self, request: MediaRequest, ydl, info: dict[str, Any]) -> MediaResult:
        output_path = self._resolve_output_path(ydl, info)
        metadata = self.build_metadata(info)
        # 모든 핸들러가 공통으로 file_size를 제공(인터페이스 일관성)
        if os.path.exists(output_path):
            metadata.setdefault("file_size", os.path.getsize(output_path))
        return MediaResult(
            media_type=self.media_type,
            source_url=request.url,
            output_path=output_path,
            title=info.get("title"),
            duration=info.get("duration"),
            metadata=metadata,
        )

    def process(self, request: MediaRequest) -> MediaResult:
        """템플릿 메서드: 옵션 구성 → 재시도 루프 → 다운로드/변환 → 결과 반환."""
        yt_dlp = _import_yt_dlp()
        os.makedirs(request.output_dir, exist_ok=True)
        options = self._compose_options(request)

        last_error: Optional[Exception] = None
        for attempt in range(1, self.retries + 1):
            try:
                with yt_dlp.YoutubeDL(options) as ydl:
                    info = ydl.extract_info(request.url, download=True)
                    return self._build_result(request, ydl, info)
            except yt_dlp.utils.DownloadError as exc:
                last_error = exc
                self.logger.warning(
                    "[%s] 시도 %d/%d 실패: %s", self.media_type, attempt, self.retries, exc
                )
                if attempt < self.retries:
                    delay = min(self.backoff_base ** attempt, self.backoff_max)
                    time.sleep(delay)

        raise MediaProcessingError(f"'{request.url}' 처리 실패: {last_error}")
