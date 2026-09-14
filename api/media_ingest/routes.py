"""미디어 인제스트 API 라우터."""

from __future__ import annotations

import asyncio
import json
import os
import queue
import shutil
import tempfile
import uuid
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool

from .audio import AudioProcessor
from .base import MediaProcessingError, MediaRequest, MediaResult
from .feeds import FeedCrawlerFactory
from .pipeline import build_default_pipeline
from .video import VideoProcessor

router = APIRouter()

# 프로세스 단위로 재사용하는 기본 파이프라인
pipeline = build_default_pipeline()

# 완료된 SSE 작업의 결과 파일 보관소: token -> (path, tmp_dir, filename, content_type)
_RESULTS: dict[str, tuple[str, str, str, str]] = {}

ALLOWED_SCHEMES = {"http", "https"}


def _url_error(url: str) -> str | None:
    """URL 검증 실패 시 메시지 반환(정상이면 None). 스트림 내부에서 사용."""
    if not url or not url.strip():
        return "URL이 필요합니다."
    scheme = urlsplit(url).scheme.lower()
    if scheme not in ALLOWED_SCHEMES:
        return f"허용되지 않은 URL 스킴입니다: {scheme!r}"
    return None


def _validate_url(url: str) -> None:
    if not url.strip():
        raise HTTPException(status_code=400, detail="URL이 필요합니다.")
    scheme = urlsplit(url).scheme.lower()
    if scheme not in ALLOWED_SCHEMES:
        # file://, ftp:// 등 로컬/비웹 스킴 차단
        raise HTTPException(status_code=400, detail=f"허용되지 않은 URL 스킴입니다: {scheme!r}")


async def _run(media_type: str, media_req: MediaRequest, tmp_dir: str) -> MediaResult:
    """블로킹 파이프라인을 스레드풀에서 실행하고 오류를 HTTP로 정규화."""
    handler = pipeline.get(media_type)
    try:
        return await run_in_threadpool(handler.process, media_req)
    except MediaProcessingError as exc:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise HTTPException(status_code=502, detail=str(exc))
    except Exception as exc:  # noqa: BLE001 - 사용자에게 400으로 정규화
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail=f"처리 중 오류: {exc}")


def _file_response(result: MediaResult, tmp_dir: str, content_type: str) -> FileResponse:
    """결과 파일 응답 + 공통 메타데이터를 헤더로 노출 + 임시 디렉터리 정리."""
    if not os.path.exists(result.output_path):
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail="변환 결과 파일을 찾을 수 없습니다.")

    info = result.to_dict()
    headers = {
        "X-Media-Type": str(info.get("media_type") or ""),
        "X-Media-File-Size": str(info.get("file_size") or ""),
        "X-Media-Duration": str(info.get("duration") or ""),
        "X-Media-Resolution": str(info.get("resolution") or ""),
    }
    return FileResponse(
        result.output_path,
        filename=os.path.basename(result.output_path),
        media_type=content_type,
        headers=headers,
        background=BackgroundTask(shutil.rmtree, tmp_dir, ignore_errors=True),
    )


@router.get("/media/handlers")
async def list_handlers():
    """현재 파이프라인에 등록된 media_type / 지원 플랫폼 목록."""
    return {
        "media_types": pipeline.media_types,
        "platforms": FeedCrawlerFactory.platforms(),
    }


@router.post("/media/feed")
async def crawl_feed(request: Request):
    """피드 식별자(채널/프로필/재생목록)에서 미디어 URL 목록만 수집(다운로드 X)."""
    data = await request.json()
    identifier = data.get("identifier", "")
    _validate_url(identifier)
    limit = data.get("limit")
    cookies = data.get("cookies_from_browser")

    try:
        adapter = FeedCrawlerFactory.for_identifier(identifier, cookies_from_browser=cookies)
        urls = await run_in_threadpool(adapter.crawl, identifier, limit)
    except MediaProcessingError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"피드 수집 오류: {exc}")

    return {
        "platform": adapter.platform,
        "feed_type": adapter.classify(identifier),
        "count": len(urls),
        "urls": urls,
    }


@router.post("/media/audio")
async def extract_audio(request: Request):
    """웹 미디어 URL에서 오디오를 추출해 MP3(기본 192k)로 반환."""
    data = await request.json()
    url = data.get("url", "")
    _validate_url(url)
    bitrate = str(data.get("bitrate", "192"))
    codec = str(data.get("codec", "mp3"))

    tmp_dir = tempfile.mkdtemp(prefix="media_ingest_")
    media_req = MediaRequest(
        url=url,
        output_dir=tmp_dir,
        options={
            "ydl_options": {
                "postprocessors": [
                    {
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": codec,
                        "preferredquality": bitrate,
                    }
                ]
            }
        },
    )

    result = await _run("audio", media_req, tmp_dir)
    content_type = "audio/mpeg" if codec == "mp3" else "application/octet-stream"
    return _file_response(result, tmp_dir, content_type)


@router.post("/media/video")
async def extract_video(request: Request):
    """웹 미디어 URL에서 최고 화질 비디오+오디오를 단일 MP4로 병합해 반환."""
    data = await request.json()
    url = data.get("url", "")
    _validate_url(url)
    container = str(data.get("container", "mp4"))
    format_spec = data.get("format")  # 선택: 커스텀 포맷 셀렉터

    tmp_dir = tempfile.mkdtemp(prefix="media_ingest_")
    ydl_options: dict = {"merge_output_format": container}
    if format_spec:
        ydl_options["format"] = str(format_spec)
    media_req = MediaRequest(
        url=url,
        output_dir=tmp_dir,
        options={"ydl_options": ydl_options},
    )

    result = await _run("video", media_req, tmp_dir)
    content_type = "video/mp4" if container == "mp4" else "application/octet-stream"
    return _file_response(result, tmp_dir, content_type)


# ---------------------------------------------------------------------------
# SSE 실시간 진행상황 스트리밍
# ---------------------------------------------------------------------------
def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def _make_handler(media_type: str, bitrate: str, callback):
    if media_type == "audio":
        return AudioProcessor(bitrate=bitrate, progress_callback=callback)
    return VideoProcessor(progress_callback=callback)


@router.get("/media/stream")
async def media_stream(request: Request, type: str = "video", url: str = "", bitrate: str = "192"):
    """처리 진행상황을 text/event-stream으로 실시간 전송.

    완료 시 phase=done 이벤트에 download 경로(/media/result/{token})를 담아준다.
    브라우저 EventSource로 소비한다.
    """
    media_type = type if type in ("audio", "video") else "video"

    async def event_gen():
        err = _url_error(url)
        if err:
            yield _sse({"phase": "error", "message": err})
            return

        events: "queue.Queue[dict]" = queue.Queue()
        tmp_dir = tempfile.mkdtemp(prefix="media_ingest_")
        handler = _make_handler(media_type, bitrate, events.put)
        media_req = MediaRequest(url=url, output_dir=tmp_dir)

        loop = asyncio.get_event_loop()
        future = loop.run_in_executor(None, handler.process, media_req)

        yield _sse({"phase": "start", "media_type": media_type, "url": url})

        # 처리 완료까지 큐를 비우며 스트리밍
        while True:
            drained = False
            try:
                while True:
                    yield _sse(events.get_nowait())
                    drained = True
            except queue.Empty:
                pass

            if future.done():
                break
            if await request.is_disconnected():
                # 스레드는 강제 종료 불가 → 결과 폐기만 예약
                future.add_done_callback(
                    lambda _f: shutil.rmtree(tmp_dir, ignore_errors=True)
                )
                return
            await asyncio.sleep(0 if drained else 0.3)

        # 남은 이벤트 소진
        try:
            while True:
                yield _sse(events.get_nowait())
        except queue.Empty:
            pass

        try:
            result: MediaResult = future.result()
        except Exception as exc:  # noqa: BLE001
            shutil.rmtree(tmp_dir, ignore_errors=True)
            yield _sse({"phase": "error", "message": str(exc)})
            return

        if not os.path.exists(result.output_path):
            shutil.rmtree(tmp_dir, ignore_errors=True)
            yield _sse({"phase": "error", "message": "결과 파일을 찾을 수 없습니다."})
            return

        token = uuid.uuid4().hex
        content_type = "audio/mpeg" if media_type == "audio" else "video/mp4"
        _RESULTS[token] = (
            result.output_path, tmp_dir, os.path.basename(result.output_path), content_type,
        )
        yield _sse({
            "phase": "done",
            "result": result.to_dict(),
            "download": f"/media/result/{token}",
        })

    headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"}
    return StreamingResponse(event_gen(), media_type="text/event-stream", headers=headers)


@router.get("/media/result/{token}")
async def media_result(token: str):
    """SSE로 완료된 작업의 결과 파일을 다운로드(1회성, 전송 후 정리)."""
    entry = _RESULTS.pop(token, None)
    if entry is None:
        raise HTTPException(status_code=404, detail="만료되었거나 존재하지 않는 결과입니다.")
    path, tmp_dir, filename, content_type = entry
    if not os.path.exists(path):
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise HTTPException(status_code=410, detail="결과 파일이 더 이상 없습니다.")
    return FileResponse(
        path,
        filename=filename,
        media_type=content_type,
        background=BackgroundTask(shutil.rmtree, tmp_dir, ignore_errors=True),
    )
