"""1~2단계: AudioProcessor / VideoProcessor + 베이스 재시도 로직 검증."""

from __future__ import annotations

import os

import pytest

from api.media_ingest import (
    AudioProcessor,
    MediaProcessingError,
    MediaRequest,
    VideoProcessor,
)


def _audio_behavior(opts, url, download):
    d = os.path.dirname(opts["outtmpl"])
    path = os.path.join(d, "song.mp3")
    if download:
        with open(path, "wb") as f:
            f.write(b"ID3-fake-audio")
    return {
        "id": "song",
        "title": "My Song",
        "ext": "mp3",
        "duration": 61.5,
        "uploader": "tester",
        "extractor": "test",
        "requested_downloads": [{"filepath": path}],
    }


def _video_behavior(opts, url, download):
    d = os.path.dirname(opts["outtmpl"])
    path = os.path.join(d, "clip.mp4")
    if download:
        with open(path, "wb") as f:
            f.write(b"\x00\x00\x00\x18ftypmp42")
    return {
        "id": "clip",
        "title": "My Clip",
        "ext": "mp4",
        "duration": 12.0,
        "width": 1920,
        "height": 1080,
        "fps": 30,
        "vcodec": "h264",
        "acodec": "aac",
        "requested_downloads": [{"filepath": path}],
    }


def test_audio_processor(tmp_path, install_fake_yt_dlp):
    install_fake_yt_dlp(_audio_behavior)
    proc = AudioProcessor(bitrate="192")
    result = proc.process(MediaRequest(url="https://x/a", output_dir=str(tmp_path)))

    assert result.media_type == "audio"
    assert result.output_path.endswith("song.mp3")
    assert result.duration == 61.5
    assert result.metadata["file_size"] == len(b"ID3-fake-audio")
    assert result.metadata["codec"] == "mp3"
    assert result.metadata["bitrate_kbps"] == "192"

    d = result.to_dict()
    assert d["file_path"] == result.output_path
    assert d["file_size"] == len(b"ID3-fake-audio")


def test_audio_ydl_options():
    proc = AudioProcessor(codec="mp3", bitrate="256")
    opts = proc.build_ydl_options(MediaRequest(url="x", output_dir="/tmp"))
    assert opts["format"] == "bestaudio/best"
    pp = opts["postprocessors"][0]
    assert pp["key"] == "FFmpegExtractAudio"
    assert pp["preferredcodec"] == "mp3"
    assert pp["preferredquality"] == "256"


def test_video_processor_muxing(tmp_path, install_fake_yt_dlp):
    install_fake_yt_dlp(_video_behavior)
    proc = VideoProcessor()
    result = proc.process(MediaRequest(url="https://x/v", output_dir=str(tmp_path)))

    assert result.media_type == "video"
    assert result.output_path.endswith("clip.mp4")
    assert result.metadata["resolution"] == "1920x1080"
    assert result.metadata["fps"] == 30
    assert result.metadata["container"] == "mp4"
    assert result.to_dict()["resolution"] == "1920x1080"


def test_video_format_and_merge():
    proc = VideoProcessor()
    opts = proc.build_ydl_options(MediaRequest(url="x", output_dir="/tmp"))
    assert opts["format"] == "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best"
    assert opts["merge_output_format"] == "mp4"


def test_retry_then_success(tmp_path, install_fake_yt_dlp):
    """DownloadError 2회 후 성공 → 최종 성공."""
    from tests.conftest import FakeDownloadError

    calls = {"n": 0}

    def flaky(opts, url, download):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise FakeDownloadError("transient network error")
        return _audio_behavior(opts, url, download)

    install_fake_yt_dlp(flaky)
    proc = AudioProcessor(retries=3)
    result = proc.process(MediaRequest(url="https://x/a", output_dir=str(tmp_path)))
    assert calls["n"] == 3
    assert result.output_path.endswith("song.mp3")


def test_retry_exhausted_raises(tmp_path, install_fake_yt_dlp):
    from tests.conftest import FakeDownloadError

    def always_fail(opts, url, download):
        raise FakeDownloadError("permanent")

    install_fake_yt_dlp(always_fail)
    proc = AudioProcessor(retries=2)
    with pytest.raises(MediaProcessingError):
        proc.process(MediaRequest(url="https://x/a", output_dir=str(tmp_path)))


def test_progress_callback_fires():
    """progress_hooks → _emit → progress_callback 경로 검증."""
    events = []
    proc = VideoProcessor(progress_callback=events.append)
    proc._progress_hook({"status": "downloading", "_percent_str": " 42% ", "_speed_str": "1MiB/s"})
    proc._postprocessor_hook({"status": "started", "postprocessor": "Merger"})

    phases = [e["phase"] for e in events]
    assert phases == ["download", "postprocess"]
    assert events[0]["percent"] == "42%"
    assert events[1]["postprocessor"] == "Merger"


def test_progress_callback_exception_is_swallowed():
    """콜백이 예외를 던져도 처리 흐름은 중단되지 않아야 한다."""
    def boom(_e):
        raise RuntimeError("consumer down")

    proc = VideoProcessor(progress_callback=boom)
    # 예외가 전파되지 않아야 함
    proc._progress_hook({"status": "downloading"})


def test_build_match_conditions():
    from api.media_ingest import build_match_conditions

    conds = build_match_conditions(
        {"max_duration": 600, "min_duration": 30, "exclude_title": "무한반복|loop"}
    )
    assert "duration >= 30" in conds
    assert "duration <= 600" in conds
    assert any(c.startswith("title !~=") and "무한반복|loop" in c for c in conds)
    # 아무 옵션 없으면 빈 목록
    assert build_match_conditions({}) == []


def test_max_duration_builds_match_filter(tmp_path):
    """max_duration 설정 시 yt-dlp match_filter(callable)가 구성돼야 한다."""
    proc = VideoProcessor()
    req = MediaRequest(
        url="x", output_dir=str(tmp_path), options={"max_duration": 600, "min_duration": 60}
    )
    opts = proc._compose_options(req)
    assert callable(opts.get("match_filter"))


def test_policy_options_threaded(tmp_path):
    """쿠키/지연 옵션이 yt-dlp 옵션으로 통과되는지."""
    proc = VideoProcessor()
    req = MediaRequest(
        url="x",
        output_dir=str(tmp_path),
        options={
            "cookies_from_browser": "chrome",
            "sleep_interval": 3,
            "max_sleep_interval": 7,
        },
    )
    opts = proc._compose_options(req)
    assert opts["cookiesfrombrowser"] == ("chrome",)
    assert opts["sleep_interval"] == 3
    assert opts["max_sleep_interval"] == 7
