"""배치 인제스천 오케스트레이터.

피드 식별자(채널/프로필/재생목록) → URL 목록 수집 → 각 URL을 오디오/비디오
파이프라인으로 처리한다. 플랫폼 정책 대응을 위해:
  - 브라우저 세션 쿠키(cookies-from-browser) 연동
  - 요청 간 무작위 지연(기본 3~7초)으로 서버 부하 완화
  - 항목별 지수 백오프 재시도(개별 실패가 전체 배치를 중단시키지 않음)
"""

from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from .base import MediaProcessingError, MediaRequest, MediaSkipped
from .feeds import FeedCrawlerFactory
from .pipeline import MediaIngestPipeline, build_default_pipeline

logger = logging.getLogger(__name__)


@dataclass
class BatchItemResult:
    url: str
    status: str  # "ok" | "failed" | "skipped"
    result: Optional[dict[str, Any]] = None
    error: Optional[str] = None


@dataclass
class BatchResult:
    identifier: str
    platform: str
    total: int
    succeeded: int
    failed: int
    skipped: int = 0
    items: list[BatchItemResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "identifier": self.identifier,
            "platform": self.platform,
            "total": self.total,
            "succeeded": self.succeeded,
            "failed": self.failed,
            "skipped": self.skipped,
            "items": [item.__dict__ for item in self.items],
        }


class BatchIngestor:
    """피드 수집 + 대량 처리 오케스트레이터."""

    def __init__(
        self,
        pipeline: Optional[MediaIngestPipeline] = None,
        *,
        media_type: str = "video",
        min_delay: float = 3.0,
        max_delay: float = 7.0,
        cookies_from_browser: Any = None,
        item_retries: int = 3,
        backoff_base: float = 2.0,
        backoff_max: float = 30.0,
        sleep_interval: Optional[float] = 3,
        max_sleep_interval: Optional[float] = 7,
        max_duration: Optional[int] = None,
        min_duration: Optional[int] = None,
        exclude_title: Optional[str] = None,
        archive: Optional[str] = None,
        overfetch: int = 5,
        logger_: Optional[logging.Logger] = None,
    ) -> None:
        self.pipeline = pipeline or build_default_pipeline()
        self.media_type = media_type
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.cookies_from_browser = cookies_from_browser
        self.item_retries = max(1, item_retries)
        self.backoff_base = backoff_base
        self.backoff_max = backoff_max
        # yt-dlp 자체의 요청 간 sleep(다운로드 레벨)도 함께 적용
        self.sleep_interval = sleep_interval
        self.max_sleep_interval = max_sleep_interval
        # 길이 필터(초): 너무 긴 무한반복/롱믹스 등을 건너뛰기 위함
        self.max_duration = max_duration
        self.min_duration = min_duration
        # 제목 정규식 제외 필터(예: "무한반복|loop|[0-9]+시간")
        self.exclude_title = exclude_title
        # 다운로드 아카이브 파일 경로(있으면 이미 받은 항목은 다음 실행 때 건너뜀)
        self.archive = archive
        # 목표(limit) 달성을 위해 후보를 몇 배로 넉넉히 수집할지
        self.overfetch = max(1, overfetch)
        self.logger = logger_ or logger

    def _random_delay(self) -> None:
        """항목 사이 무작위 지연으로 속도 제한을 회피(서버 부하 완화)."""
        delay = random.uniform(self.min_delay, self.max_delay)
        self.logger.info("다음 항목까지 %.1f초 대기", delay)
        time.sleep(delay)

    def _request_options(self) -> dict[str, Any]:
        opts: dict[str, Any] = {}
        if self.cookies_from_browser:
            opts["cookies_from_browser"] = self.cookies_from_browser
        if self.sleep_interval is not None:
            opts["sleep_interval"] = self.sleep_interval
        if self.max_sleep_interval is not None:
            opts["max_sleep_interval"] = self.max_sleep_interval
        if self.max_duration is not None:
            opts["max_duration"] = self.max_duration
        if self.min_duration is not None:
            opts["min_duration"] = self.min_duration
        if self.exclude_title:
            opts["exclude_title"] = self.exclude_title
        if self.archive:
            opts["download_archive"] = self.archive
        return opts

    def _process_one(self, url: str, output_dir: str) -> dict[str, Any]:
        """단일 URL을 지수 백오프로 재시도하며 처리. (MediaSkipped는 재시도 없이 전파)"""
        last_error: Optional[Exception] = None
        for attempt in range(1, self.item_retries + 1):
            try:
                req = MediaRequest(url=url, output_dir=output_dir, options=self._request_options())
                result = self.pipeline.process(self.media_type, req)
                return result.to_dict()
            except MediaProcessingError as exc:
                last_error = exc
                self.logger.warning(
                    "항목 처리 실패 %d/%d (%s): %s", attempt, self.item_retries, url, exc
                )
                if attempt < self.item_retries:
                    delay = min(self.backoff_base ** attempt, self.backoff_max)
                    time.sleep(delay)
        raise MediaProcessingError(f"'{url}' 처리 실패: {last_error}")

    def ingest(self, identifier: str, output_dir: str, limit: Optional[int] = None) -> BatchResult:
        """식별자로부터 피드를 수집하고 URL을 처리한다.

        limit이 주어지면 그 수만큼 **성공(다운로드)** 할 때까지 처리한다. 필터/중복으로
        건너뛴 항목은 목표에 포함되지 않으므로, 후보를 넉넉히(overfetch) 수집해 백필한다.
        """
        adapter = FeedCrawlerFactory.for_identifier(
            identifier, cookies_from_browser=self.cookies_from_browser
        )
        # 목표(limit)보다 많이 수집해두고, 성공 개수가 채워지면 멈춘다.
        candidate_cap = limit * self.overfetch if limit else None
        urls = adapter.crawl(identifier, limit=candidate_cap)

        items: list[BatchItemResult] = []
        succeeded = 0
        for url in urls:
            if limit and succeeded >= limit:
                break
            if items:  # 첫 시도 제외, 항목 사이 지연
                self._random_delay()
            try:
                data = self._process_one(url, output_dir)
                items.append(BatchItemResult(url=url, status="ok", result=data))
                succeeded += 1
            except MediaSkipped as exc:
                self.logger.info("건너뜀: %s (%s)", url, exc)
                items.append(BatchItemResult(url=url, status="skipped", error=str(exc)))
            except Exception as exc:  # noqa: BLE001 - 개별 실패는 배치를 중단시키지 않음
                self.logger.error("최종 실패: %s (%s)", url, exc)
                items.append(BatchItemResult(url=url, status="failed", error=str(exc)))

        skipped = sum(1 for i in items if i.status == "skipped")
        failed = sum(1 for i in items if i.status == "failed")
        if limit and succeeded < limit:
            self.logger.warning(
                "목표 %d개 중 %d개만 확보(후보 %d개 소진). "
                "--overfetch를 늘리거나 필터를 완화하세요.",
                limit, succeeded, len(urls),
            )
        return BatchResult(
            identifier=identifier,
            platform=adapter.platform,
            total=len(items),
            succeeded=succeeded,
            failed=failed,
            skipped=skipped,
            items=items,
        )


# ---------------------------------------------------------------------------
# 단일 실행 진입점 (전체 파이프라인 통합 CLI)
#   python -m api.media_ingest.batch <identifier> [옵션]
# ---------------------------------------------------------------------------
def _build_arg_parser():
    import argparse

    parser = argparse.ArgumentParser(
        prog="media-ingest",
        description="멀티 플랫폼 피드 배치 인제스천 (오디오/비디오)",
    )
    parser.add_argument(
        "identifier", nargs="?", default=None,
        help="채널/프로필/재생목록 URL 또는 식별자 (--search 사용 시 생략)",
    )
    parser.add_argument(
        "--search", default=None,
        help="유튜브 키워드 검색 (identifier 대신 사용, 예: --search '로파이 음악')",
    )
    parser.add_argument(
        "-t", "--type", dest="media_type", default="video",
        choices=["audio", "video"], help="처리 유형 (기본: video)",
    )
    parser.add_argument("-o", "--output", default="./downloads", help="저장 디렉터리")
    parser.add_argument(
        "-n", "--limit", type=int, default=None,
        help="최대 항목 수 (피드: 미지정 시 전체 / --search: 미지정 시 20)",
    )
    parser.add_argument(
        "--cookies-from-browser", default=None,
        help="브라우저 세션 쿠키 사용 (예: chrome, firefox)",
    )
    parser.add_argument("--min-delay", type=float, default=3.0, help="항목 간 최소 지연(초)")
    parser.add_argument("--max-delay", type=float, default=7.0, help="항목 간 최대 지연(초)")
    parser.add_argument("--retries", type=int, default=3, help="항목별 재시도 횟수")
    parser.add_argument(
        "--max-duration", type=int, default=None,
        help="이 길이(초)를 넘는 항목은 건너뜀 (예: 1200=20분). 긴 무한반복/롱믹스 제외용",
    )
    parser.add_argument(
        "--min-duration", type=int, default=None,
        help="이 길이(초) 미만 항목은 건너뜀",
    )
    parser.add_argument(
        "--exclude-title", default=None,
        help="제목이 이 정규식에 매칭되면 건너뜀 (대소문자 무시). "
             "예: '무한반복|loop|[0-9]+\\s*시간|수면|asmr'",
    )
    parser.add_argument(
        "--archive", default=None,
        help="다운로드 아카이브 파일 경로. 이미 받은 항목은 다음 실행 때 건너뜀(중복 방지)",
    )
    parser.add_argument(
        "--overfetch", type=int, default=5,
        help="목표(-n) 대비 후보 수집 배수 (필터/중복 대비 백필용, 기본 5)",
    )
    parser.add_argument("--crawl-only", action="store_true", help="다운로드 없이 URL 목록만 출력")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    import json

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    # 키워드 검색이면 식별자를 ytsearch 형태로 생성
    from .feeds import YouTubeSearchAdapter

    identifier = args.identifier
    if args.search:
        identifier = YouTubeSearchAdapter.build_query(args.search, args.limit)
    if not identifier:
        parser.error("identifier 또는 --search 중 하나는 필요합니다.")

    if args.crawl_only:
        adapter = FeedCrawlerFactory.for_identifier(
            identifier, cookies_from_browser=args.cookies_from_browser
        )
        urls = adapter.crawl(identifier, limit=args.limit)
        print(json.dumps({"platform": adapter.platform, "urls": urls}, ensure_ascii=False, indent=2))
        return 0

    ingestor = BatchIngestor(
        media_type=args.media_type,
        min_delay=args.min_delay,
        max_delay=args.max_delay,
        cookies_from_browser=args.cookies_from_browser,
        item_retries=args.retries,
        max_duration=args.max_duration,
        min_duration=args.min_duration,
        exclude_title=args.exclude_title,
        archive=args.archive,
        overfetch=args.overfetch,
    )
    result = ingestor.ingest(identifier, args.output, limit=args.limit)
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0 if result.failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
