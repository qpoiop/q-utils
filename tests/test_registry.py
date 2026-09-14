"""모듈 레지스트리(선택적 활성화) 검증."""

from __future__ import annotations

from fastapi import FastAPI

from api.registry import (
    Feature,
    available_modules,
    enabled_modules,
    load_features,
    register_features,
)


def test_available_modules():
    assert set(available_modules()) == {"html_to_pdf", "media_ingest"}


def test_enabled_default_is_all(monkeypatch):
    monkeypatch.delenv("Q_UTILS_MODULES", raising=False)
    assert set(enabled_modules()) == set(available_modules())


def test_enabled_subset(monkeypatch):
    monkeypatch.setenv("Q_UTILS_MODULES", "media_ingest")
    assert enabled_modules() == ["media_ingest"]


def test_enabled_ignores_unknown(monkeypatch):
    monkeypatch.setenv("Q_UTILS_MODULES", " media_ingest , nope , html_to_pdf ")
    assert enabled_modules() == ["media_ingest", "html_to_pdf"]


def test_load_media_feature():
    features = load_features(["media_ingest"])
    assert len(features) == 1
    assert isinstance(features[0], Feature)
    assert features[0].name == "media_ingest"


def test_html_to_pdf_loads_without_wkhtmltopdf():
    """지연 초기화 덕분에 wkhtmltopdf 바이너리 없이도 모듈 로드가 성공해야 한다."""
    features = load_features(["html_to_pdf"])
    assert features[0].name == "html_to_pdf"
    # 라우터에 web/API 경로가 모두 존재
    paths = {r.path for r in features[0].router.routes}
    assert {"/convert", "/convert_url", "/html_to_pdf", "/url_to_pdf"} <= paths


def test_register_only_selected_module():
    app = FastAPI()
    registered = register_features(app, prefix="/api", names=["media_ingest"])
    assert registered == ["media_ingest"]
    # 선택된 모듈의 라우터만 조립됨: media 경로 존재, PDF(/convert) 미포함
    media_paths = {r.path for r in load_features(["media_ingest"])[0].router.routes if hasattr(r, "path")}
    assert any(p.startswith("/media") for p in media_paths)
    assert not any(p in ("/convert", "/convert_url") for p in media_paths)
