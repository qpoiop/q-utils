"""공용 테스트 픽스처: 네트워크 없이 도는 가짜 yt_dlp 주입."""

from __future__ import annotations

import os
import sys
import types

import pytest


class FakeDownloadError(Exception):
    """yt_dlp.utils.DownloadError 대체."""


def _install_fake_yt_dlp(monkeypatch, behavior):
    """behavior(opts, url, download) -> info dict 로 동작하는 가짜 yt_dlp 설치.

    base._import_yt_dlp() 가 `import yt_dlp` 하므로 sys.modules에 주입한다.
    """
    mod = types.ModuleType("yt_dlp")
    utils = types.ModuleType("yt_dlp.utils")
    utils.DownloadError = FakeDownloadError
    mod.utils = utils

    class FakeYDL:
        def __init__(self, opts):
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def extract_info(self, url, download=False):
            return behavior(self.opts, url, download)

        def prepare_filename(self, info):
            outtmpl = self.opts.get("outtmpl", "out.%(ext)s")
            d = os.path.dirname(outtmpl)
            return os.path.join(d, f"{info.get('id', 'x')}.{info.get('ext', 'bin')}")

    mod.YoutubeDL = FakeYDL
    monkeypatch.setitem(sys.modules, "yt_dlp", mod)
    monkeypatch.setitem(sys.modules, "yt_dlp.utils", utils)
    return mod


@pytest.fixture
def install_fake_yt_dlp(monkeypatch):
    """테스트에서 behavior를 넘겨 가짜 yt_dlp를 설치하는 팩토리 픽스처."""

    def _factory(behavior):
        return _install_fake_yt_dlp(monkeypatch, behavior)

    return _factory


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """모든 테스트에서 실제 대기를 제거해 즉시 실행."""
    import time

    monkeypatch.setattr(time, "sleep", lambda *a, **k: None)
