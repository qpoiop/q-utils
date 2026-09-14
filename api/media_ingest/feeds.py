"""멀티 플랫폼 피드 크롤러 어댑터 레이어.

채널/프로필/재생목록 같은 '피드 식별자'로부터 개별 미디어 URL 목록을 수집한다.
yt-dlp의 flat 추출(extract_flat)을 사용해 다운로드 없이 항목만 열거한다.

플랫폼별 어댑터는 다음을 차별화한다:
  - classify(): 식별자가 어떤 피드 유형인지(channel/playlist/profile/video/...) 분류
  - normalize_identifier(): 열거에 적합한 형태로 URL 정규화(예: YouTube 채널 → 업로드 탭)
  - before_crawl(): 크롤 전 정책 점검(예: 인스타 프로필은 쿠키 필요 경고)
  - _entry_to_url(): flat 항목에서 최종 미디어 URL 복원(플랫폼별 규칙)

주의: 유튜브/인스타그램/틱톡은 자동 수집을 약관으로 제한한다. 접근 권한이 있는
대상(본인 콘텐츠, 권한 있는 계정, 공개 아카이빙 등)에만 사용하고 각 플랫폼의
ToS·저작권·로봇배제 정책을 준수할 것.
"""

from __future__ import annotations

import logging
import re
from abc import ABC
from typing import Any, ClassVar, Optional

from .base import (
    MediaProcessingError,
    _import_yt_dlp,
    normalize_cookies_from_browser,
)

logger = logging.getLogger(__name__)


class FeedCrawlerAdapter(ABC):
    """피드 식별자 → 미디어 URL 목록 수집기의 추상 인터페이스."""

    platform: ClassVar[str] = "base"
    # 이 어댑터가 처리할 수 있는 식별자 URL 패턴들
    patterns: ClassVar[list[re.Pattern]] = []

    def __init__(
        self,
        *,
        cookies_from_browser: Any = None,
        quiet: bool = True,
        logger_: Optional[logging.Logger] = None,
    ) -> None:
        self.cookies_from_browser = normalize_cookies_from_browser(cookies_from_browser)
        self.quiet = quiet
        self.logger = logger_ or logging.getLogger(f"{__name__}.{self.platform}")

    @classmethod
    def matches(cls, identifier: str) -> bool:
        return any(p.search(identifier) for p in cls.patterns)

    # ----- 플랫폼별 확장 지점 -----
    def classify(self, identifier: str) -> str:
        """식별자의 피드 유형을 분류. 서브클래스가 재정의."""
        return "unknown"

    def normalize_identifier(self, identifier: str) -> str:
        """열거에 적합한 형태로 URL 정규화. 기본은 그대로."""
        return identifier

    def before_crawl(self, identifier: str) -> None:
        """크롤 직전 정책 점검 훅. 기본은 no-op."""

    def build_crawl_options(self) -> dict[str, Any]:
        """플랫폼별 추가 크롤 옵션(선택). 기본은 없음."""
        return {}

    def _entry_to_url(self, entry: dict[str, Any]) -> Optional[str]:
        return entry.get("url") or entry.get("webpage_url")

    # ----- 공통 로직 -----
    def _crawl_options(self, limit: Optional[int]) -> dict[str, Any]:
        opts: dict[str, Any] = {
            "quiet": self.quiet,
            "no_warnings": self.quiet,
            "skip_download": True,
            "extract_flat": "in_playlist",  # 항목 열거만, 개별 메타 재귀 X
        }
        if self.cookies_from_browser:
            opts["cookiesfrombrowser"] = self.cookies_from_browser
        if limit:
            opts["playlistend"] = int(limit)
        opts.update(self.build_crawl_options())
        return opts

    @staticmethod
    def _iter_entries(info: dict[str, Any]):
        """channel(탭)→playlist→video 처럼 중첩된 entries를 평탄화."""
        entries = info.get("entries")
        if not entries:
            yield info
            return
        for entry in entries:
            if entry is None:
                continue
            if entry.get("entries"):
                yield from FeedCrawlerAdapter._iter_entries(entry)
            else:
                yield entry

    def describe(self, identifier: str) -> dict[str, Any]:
        """다운로드 없이 식별자를 진단(플랫폼/유형/정규화 결과)."""
        return {
            "platform": self.platform,
            "feed_type": self.classify(identifier),
            "normalized": self.normalize_identifier(identifier),
        }

    def crawl(self, identifier: str, limit: Optional[int] = None) -> list[str]:
        """식별자에서 미디어 URL 목록을 수집한다."""
        yt_dlp = _import_yt_dlp()
        target = self.normalize_identifier(identifier)
        self.before_crawl(target)
        self.logger.info(
            "[%s] 피드 크롤: %s (type=%s, limit=%s)",
            self.platform, target, self.classify(identifier), limit,
        )
        try:
            with yt_dlp.YoutubeDL(self._crawl_options(limit)) as ydl:
                info = ydl.extract_info(target, download=False)
        except yt_dlp.utils.DownloadError as exc:
            raise MediaProcessingError(f"[{self.platform}] 피드 수집 실패: {exc}") from exc

        urls: list[str] = []
        for entry in self._iter_entries(info or {}):
            url = self._entry_to_url(entry)
            if url:
                urls.append(url)
            if limit and len(urls) >= limit:
                break
        self.logger.info("[%s] 수집된 항목 수: %d", self.platform, len(urls))
        return urls


class FeedCrawlerFactory:
    """식별자를 정규식으로 판별해 알맞은 어댑터를 생성하는 팩토리."""

    _adapters: list[type[FeedCrawlerAdapter]] = []

    @classmethod
    def register(cls, adapter_cls: type[FeedCrawlerAdapter]) -> type[FeedCrawlerAdapter]:
        cls._adapters.append(adapter_cls)
        return adapter_cls

    @classmethod
    def detect(cls, identifier: str) -> Optional[type[FeedCrawlerAdapter]]:
        for adapter_cls in cls._adapters:
            if adapter_cls.matches(identifier):
                return adapter_cls
        return None

    @classmethod
    def for_identifier(cls, identifier: str, **kwargs: Any) -> FeedCrawlerAdapter:
        adapter_cls = cls.detect(identifier)
        if adapter_cls is None:
            raise MediaProcessingError(
                f"지원하지 않는 플랫폼 식별자입니다: {identifier!r} "
                f"(등록된 플랫폼: {[a.platform for a in cls._adapters]})"
            )
        return adapter_cls(**kwargs)

    @classmethod
    def platforms(cls) -> list[str]:
        return [a.platform for a in cls._adapters]


# ---------------------------------------------------------------------------
# 플랫폼별 어댑터
# ---------------------------------------------------------------------------
@FeedCrawlerFactory.register
class YouTubeFeedAdapter(FeedCrawlerAdapter):
    platform = "youtube"
    patterns = [re.compile(r"(?:youtube\.com|youtu\.be)", re.IGNORECASE)]

    _RE_PLAYLIST = re.compile(r"[?&]list=", re.IGNORECASE)
    _RE_VIDEO = re.compile(r"(?:watch\?v=|youtu\.be/|/shorts/)", re.IGNORECASE)
    _RE_CHANNEL = re.compile(r"youtube\.com/(?:channel/|c/|user/|@)[\w.\-]+", re.IGNORECASE)
    _CHANNEL_TABS = ("/videos", "/streams", "/shorts", "/playlists", "/featured")

    def classify(self, identifier: str) -> str:
        if self._RE_PLAYLIST.search(identifier):
            return "playlist"
        if self._RE_VIDEO.search(identifier):
            return "video"
        if self._RE_CHANNEL.search(identifier):
            return "channel"
        return "unknown"

    def normalize_identifier(self, identifier: str) -> str:
        # 채널 루트면 업로드(/videos) 탭으로 정규화해 전체 업로드를 열거
        if self.classify(identifier) == "channel":
            stripped = identifier.rstrip("/")
            if not stripped.lower().endswith(self._CHANNEL_TABS):
                return stripped + "/videos"
        return identifier

    def _entry_to_url(self, entry: dict[str, Any]) -> Optional[str]:
        url = super()._entry_to_url(entry)
        if url:
            return url
        vid = entry.get("id")
        return f"https://www.youtube.com/watch?v={vid}" if vid else None


@FeedCrawlerFactory.register
class YouTubeSearchAdapter(YouTubeFeedAdapter):
    """유튜브 키워드 검색. `ytsearchN:키워드` 형태의 식별자를 처리한다."""

    platform = "youtube_search"
    # ytsearch10:키워드 / ytsearchdate5:키워드 등
    patterns = [re.compile(r"^yt(?:search|searchdate)\d*:", re.IGNORECASE)]

    def classify(self, identifier: str) -> str:
        return "search"

    def normalize_identifier(self, identifier: str) -> str:
        # 검색 식별자는 그대로 사용(채널 정규화 로직을 타지 않도록 override)
        return identifier

    @staticmethod
    def build_query(keyword: str, limit: int | None) -> str:
        """키워드 → yt-dlp 검색 식별자 문자열."""
        n = limit if limit and limit > 0 else 20
        return f"ytsearch{n}:{keyword}"


@FeedCrawlerFactory.register
class InstagramFeedAdapter(FeedCrawlerAdapter):
    platform = "instagram"
    patterns = [re.compile(r"instagram\.com", re.IGNORECASE)]

    _RE_POST = re.compile(r"instagram\.com/(?:p|reel|reels|tv)/[\w\-]+", re.IGNORECASE)
    _RE_PROFILE = re.compile(r"instagram\.com/[\w.]+/?(?:\?.*)?$", re.IGNORECASE)

    def classify(self, identifier: str) -> str:
        if self._RE_POST.search(identifier):
            return "post"
        if self._RE_PROFILE.search(identifier):
            return "profile"
        return "unknown"

    def before_crawl(self, identifier: str) -> None:
        # 인스타 프로필 피드는 대개 로그인 세션(쿠키)이 필요하다.
        if self.classify(identifier) == "profile" and not self.cookies_from_browser:
            self.logger.warning(
                "[instagram] 프로필 피드에는 cookies_from_browser가 필요할 수 있음 "
                "(미설정 시 로그인 요구/빈 결과 가능)"
            )


@FeedCrawlerFactory.register
class TikTokFeedAdapter(FeedCrawlerAdapter):
    platform = "tiktok"
    patterns = [re.compile(r"tiktok\.com", re.IGNORECASE)]

    _RE_VIDEO = re.compile(r"tiktok\.com/@[\w.\-]+/video/\d+", re.IGNORECASE)
    _RE_USER = re.compile(r"tiktok\.com/@[\w.\-]+/?(?:\?.*)?$", re.IGNORECASE)

    def classify(self, identifier: str) -> str:
        if self._RE_VIDEO.search(identifier):
            return "video"
        if self._RE_USER.search(identifier):
            return "user"
        return "unknown"

    def before_crawl(self, identifier: str) -> None:
        if self.classify(identifier) == "user" and not self.cookies_from_browser:
            self.logger.warning(
                "[tiktok] 유저 피드 열거는 지역/봇 차단에 민감함 "
                "(cookies_from_browser 및 지연 설정 권장)"
            )
