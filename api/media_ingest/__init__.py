"""미디어 인제스트 파이프라인 패키지."""

from .audio import AudioProcessor
from .base import (
    BaseMediaHandler,
    HANDLER_REGISTRY,
    MediaProcessingError,
    MediaRequest,
    MediaResult,
    normalize_cookies_from_browser,
    register_handler,
)
from .batch import BatchIngestor, BatchItemResult, BatchResult
from .feeds import (
    FeedCrawlerAdapter,
    FeedCrawlerFactory,
    InstagramFeedAdapter,
    TikTokFeedAdapter,
    YouTubeFeedAdapter,
    YouTubeSearchAdapter,
)
from .pipeline import MediaIngestPipeline, build_default_pipeline
from .routes import router as _router
from .video import VideoProcessor

from api.registry import Feature

FEATURE = Feature(
    name="media_ingest",
    router=_router,
    description="오디오/비디오 인제스트 (yt-dlp + ffmpeg) 및 피드 배치",
)

__all__ = [
    "FEATURE",
    "AudioProcessor",
    "VideoProcessor",
    "BaseMediaHandler",
    "HANDLER_REGISTRY",
    "MediaProcessingError",
    "MediaRequest",
    "MediaResult",
    "normalize_cookies_from_browser",
    "register_handler",
    "MediaIngestPipeline",
    "build_default_pipeline",
    "FeedCrawlerAdapter",
    "FeedCrawlerFactory",
    "YouTubeFeedAdapter",
    "YouTubeSearchAdapter",
    "InstagramFeedAdapter",
    "TikTokFeedAdapter",
    "BatchIngestor",
    "BatchItemResult",
    "BatchResult",
]
