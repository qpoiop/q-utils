"""3단계: 팩토리 / 피드 크롤러 / 배치 인제스천 검증."""

from __future__ import annotations

import pytest

from api.media_ingest import (
    BatchIngestor,
    FeedCrawlerFactory,
    MediaProcessingError,
    MediaRequest,
    MediaResult,
    MediaSkipped,
    normalize_cookies_from_browser,
)
from api.media_ingest.feeds import (
    InstagramFeedAdapter,
    TikTokFeedAdapter,
    YouTubeFeedAdapter,
    YouTubeSearchAdapter,
)


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://www.youtube.com/@LinusTechTips", YouTubeFeedAdapter),
        ("https://youtu.be/abc123", YouTubeFeedAdapter),
        ("https://www.instagram.com/nasa/", InstagramFeedAdapter),
        ("https://www.tiktok.com/@someone", TikTokFeedAdapter),
    ],
)
def test_factory_detect(url, expected):
    assert FeedCrawlerFactory.detect(url) is expected


def test_factory_detect_search():
    assert FeedCrawlerFactory.detect("ytsearch10:로파이 음악") is YouTubeSearchAdapter
    # 채널 URL은 검색 어댑터로 잡히면 안 됨
    assert FeedCrawlerFactory.detect("https://youtube.com/@x") is YouTubeFeedAdapter


def test_search_build_query():
    assert YouTubeSearchAdapter.build_query("고양이", 5) == "ytsearch5:고양이"
    # limit 없으면 기본 20
    assert YouTubeSearchAdapter.build_query("고양이", None) == "ytsearch20:고양이"


def test_search_classify_and_normalize():
    a = YouTubeSearchAdapter()
    q = "ytsearch3:재즈"
    assert a.classify(q) == "search"
    # 검색 식별자는 정규화로 /videos 가 붙지 않아야 함
    assert a.normalize_identifier(q) == q


def test_factory_unsupported():
    assert FeedCrawlerFactory.detect("https://vimeo.com/123") is None
    with pytest.raises(MediaProcessingError):
        FeedCrawlerFactory.for_identifier("https://vimeo.com/123")


def test_factory_platforms():
    assert set(FeedCrawlerFactory.platforms()) == {
        "youtube", "youtube_search", "instagram", "tiktok",
    }


@pytest.mark.parametrize(
    "value,expected",
    [
        ("chrome", ("chrome",)),
        (("firefox", "Profile 1"), ("firefox", "Profile 1")),
        (None, None),
    ],
)
def test_cookies_normalize(value, expected):
    assert normalize_cookies_from_browser(value) == expected


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://www.youtube.com/@LinusTechTips", "channel"),
        ("https://www.youtube.com/channel/UCabc123", "channel"),
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "video"),
        ("https://youtu.be/dQw4w9WgXcQ", "video"),
        ("https://www.youtube.com/playlist?list=PL123", "playlist"),
    ],
)
def test_youtube_classify(url, expected):
    assert YouTubeFeedAdapter().classify(url) == expected


def test_youtube_channel_normalized_to_uploads():
    a = YouTubeFeedAdapter()
    assert a.normalize_identifier("https://www.youtube.com/@ch").endswith("/videos")
    # 이미 탭이 붙어 있으면 그대로
    assert a.normalize_identifier("https://www.youtube.com/@ch/streams").endswith("/streams")
    # 단일 영상은 정규화하지 않음
    v = "https://youtu.be/dQw4w9WgXcQ"
    assert a.normalize_identifier(v) == v


def test_youtube_entry_url_reconstruction():
    a = YouTubeFeedAdapter()
    assert a._entry_to_url({"id": "abc123"}) == "https://www.youtube.com/watch?v=abc123"
    assert a._entry_to_url({"url": "https://v/x"}) == "https://v/x"


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://www.instagram.com/nasa/", "profile"),
        ("https://www.instagram.com/p/CabcDEF/", "post"),
        ("https://www.instagram.com/reel/CxyZ/", "post"),
    ],
)
def test_instagram_classify(url, expected):
    assert InstagramFeedAdapter().classify(url) == expected


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://www.tiktok.com/@user", "user"),
        ("https://www.tiktok.com/@user/video/123456", "video"),
    ],
)
def test_tiktok_classify(url, expected):
    assert TikTokFeedAdapter().classify(url) == expected


def _feed_behavior(opts, url, download):
    # channel → tab(entries) → video 중첩 구조 평탄화 확인
    return {
        "entries": [
            {"url": "https://v/1"},
            {"entries": [{"url": "https://v/2"}, {"webpage_url": "https://v/3"}]},
            None,  # 무시되어야 함
        ]
    }


def test_crawl_flatten(install_fake_yt_dlp):
    install_fake_yt_dlp(_feed_behavior)
    adapter = YouTubeFeedAdapter()
    urls = adapter.crawl("https://youtube.com/@x")
    assert urls == ["https://v/1", "https://v/2", "https://v/3"]


def test_crawl_limit(install_fake_yt_dlp):
    install_fake_yt_dlp(_feed_behavior)
    adapter = YouTubeFeedAdapter()
    urls = adapter.crawl("https://youtube.com/@x", limit=2)
    assert urls == ["https://v/1", "https://v/2"]


def test_crawl_error_wrapped(install_fake_yt_dlp):
    from tests.conftest import FakeDownloadError

    def boom(opts, url, download):
        raise FakeDownloadError("blocked")

    install_fake_yt_dlp(boom)
    with pytest.raises(MediaProcessingError):
        YouTubeFeedAdapter().crawl("https://youtube.com/@x")


# --- 배치 오케스트레이션 ---
class _FakeAdapter:
    platform = "youtube"

    def __init__(self, urls):
        self._urls = urls

    def crawl(self, identifier, limit=None):
        return self._urls[:limit] if limit else self._urls


class _FakePipeline:
    """지정한 URL은 실패/건너뜀, 나머지는 성공하는 가짜 파이프라인."""

    def __init__(self, fail_urls=(), skip_urls=()):
        self.fail_urls = set(fail_urls)
        self.skip_urls = set(skip_urls)
        self.calls = []

    def process(self, media_type, request: MediaRequest) -> MediaResult:
        self.calls.append(request.url)
        if request.url in self.skip_urls:
            raise MediaSkipped(f"skip {request.url}")
        if request.url in self.fail_urls:
            raise MediaProcessingError(f"fail {request.url}")
        return MediaResult(
            media_type=media_type,
            source_url=request.url,
            output_path=f"/tmp/{request.url.rsplit('/', 1)[-1]}.mp4",
            duration=1.0,
            metadata={"file_size": 10, "resolution": "1280x720"},
        )


@pytest.fixture
def patch_factory(monkeypatch):
    def _apply(urls):
        adapter = _FakeAdapter(urls)
        monkeypatch.setattr(
            FeedCrawlerFactory, "for_identifier", classmethod(lambda cls, i, **k: adapter)
        )
        return adapter

    return _apply


def test_batch_all_success(monkeypatch, patch_factory):
    patch_factory(["https://v/1", "https://v/2", "https://v/3"])
    pipe = _FakePipeline()
    ing = BatchIngestor(pipeline=pipe, media_type="video")
    delays = {"n": 0}
    monkeypatch.setattr(ing, "_random_delay", lambda: delays.__setitem__("n", delays["n"] + 1))

    res = ing.ingest("https://youtube.com/@x", "/tmp/out")
    assert res.total == 3
    assert res.succeeded == 3
    assert res.failed == 0
    assert pipe.calls == ["https://v/1", "https://v/2", "https://v/3"]
    # 항목 사이에만 지연(첫 항목 제외) → 2회
    assert delays["n"] == 2
    assert res.items[0].result["resolution"] == "1280x720"


def test_batch_partial_failure(monkeypatch, patch_factory):
    patch_factory(["https://v/1", "https://v/2", "https://v/3"])
    pipe = _FakePipeline(fail_urls=["https://v/2"])
    ing = BatchIngestor(pipeline=pipe, media_type="video", item_retries=2)
    monkeypatch.setattr(ing, "_random_delay", lambda: None)

    res = ing.ingest("https://youtube.com/@x", "/tmp/out")
    assert res.total == 3
    assert res.succeeded == 2
    assert res.failed == 1
    failed = [i for i in res.items if i.status == "failed"]
    assert len(failed) == 1
    assert failed[0].url == "https://v/2"
    # 실패 항목은 item_retries(2)회 재시도 → v/2가 2번 호출
    assert pipe.calls.count("https://v/2") == 2


def test_batch_skipped(monkeypatch, patch_factory):
    patch_factory(["https://v/1", "https://v/2", "https://v/3"])
    pipe = _FakePipeline(skip_urls=["https://v/2"])
    ing = BatchIngestor(pipeline=pipe, media_type="audio", item_retries=3)
    monkeypatch.setattr(ing, "_random_delay", lambda: None)

    res = ing.ingest("https://youtube.com/@x", "/tmp/out")
    assert res.total == 3
    assert res.succeeded == 2
    assert res.skipped == 1
    assert res.failed == 0
    # 건너뜀은 재시도하지 않음 → v/2는 한 번만 호출
    assert pipe.calls.count("https://v/2") == 1


def test_batch_duration_options():
    ing = BatchIngestor(max_duration=1200, min_duration=30, exclude_title="무한반복|loop")
    opts = ing._request_options()
    assert opts["max_duration"] == 1200
    assert opts["min_duration"] == 30
    assert opts["exclude_title"] == "무한반복|loop"


def test_batch_archive_option():
    ing = BatchIngestor(archive="/data/archive.txt")
    assert ing._request_options()["download_archive"] == "/data/archive.txt"


def test_batch_backfill_to_target(monkeypatch, patch_factory):
    """건너뛴 항목은 목표에 안 세고, 다음 후보로 백필해 목표 성공 개수를 채운다."""
    patch_factory([f"https://v/{i}" for i in range(1, 6)])  # 후보 5개
    pipe = _FakePipeline(skip_urls=["https://v/1", "https://v/2"])
    ing = BatchIngestor(pipeline=pipe, media_type="audio", overfetch=5)
    monkeypatch.setattr(ing, "_random_delay", lambda: None)

    res = ing.ingest("https://youtube.com/@x", "/tmp", limit=2)
    assert res.succeeded == 2
    assert res.skipped == 2
    # v/1,v/2 건너뜀 → v/3,v/4 성공(목표 2 달성) → v/5 는 처리 안 함
    assert pipe.calls == ["https://v/1", "https://v/2", "https://v/3", "https://v/4"]


def test_batch_request_options():
    ing = BatchIngestor(cookies_from_browser="chrome", sleep_interval=3, max_sleep_interval=7)
    opts = ing._request_options()
    assert opts["cookies_from_browser"] == "chrome"
    assert opts["sleep_interval"] == 3
    assert opts["max_sleep_interval"] == 7
