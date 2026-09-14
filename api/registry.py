"""기능 모듈 레지스트리 (선택적 활성화).

각 기능 패키지는 `FEATURE = Feature(name, router, ...)` 를 노출한다.
활성 모듈은 환경변수 `Q_UTILS_MODULES`(콤마 구분)로 선택하며, 미설정 시 전체가 켜진다.
비활성 모듈은 import조차 하지 않으므로 해당 모듈의 의존성(예: wkhtmltopdf)도 필요 없다.

예)
    Q_UTILS_MODULES=media_ingest              # 미디어만
    Q_UTILS_MODULES=html_to_pdf,media_ingest  # 둘 다
"""

from __future__ import annotations

import importlib
import logging
import os
from dataclasses import dataclass

from fastapi import APIRouter, FastAPI

logger = logging.getLogger(__name__)


@dataclass
class Feature:
    """앱에 편입 가능한 기능 모듈 디스크립터."""

    name: str
    router: APIRouter
    description: str = ""


# name -> "패키지 경로" (지연 import: 비활성 모듈은 로드하지 않음)
_MODULE_PATHS: dict[str, str] = {
    "html_to_pdf": "api.html_to_pdf",
    "media_ingest": "api.media_ingest",
}


def available_modules() -> list[str]:
    """등록된(설치 가능한) 전체 모듈 이름."""
    return list(_MODULE_PATHS)


def enabled_modules() -> list[str]:
    """환경변수로 선택된 활성 모듈 목록. 미설정 시 전체."""
    env = os.getenv("Q_UTILS_MODULES", "").strip()
    if not env:
        return available_modules()
    requested = [m.strip() for m in env.split(",") if m.strip()]
    result: list[str] = []
    for name in requested:
        if name in _MODULE_PATHS:
            result.append(name)
        else:
            logger.warning("알 수 없는 모듈 무시: %s (사용 가능: %s)", name, available_modules())
    return result


def load_features(names: list[str] | None = None) -> list[Feature]:
    """활성 모듈의 FEATURE 디스크립터를 지연 import로 로드."""
    names = names if names is not None else enabled_modules()
    features: list[Feature] = []
    for name in names:
        module = importlib.import_module(_MODULE_PATHS[name])
        feature = getattr(module, "FEATURE", None)
        if not isinstance(feature, Feature):
            logger.error("모듈 %s 가 FEATURE 디스크립터를 노출하지 않음 — 건너뜀", name)
            continue
        features.append(feature)
    return features


def register_features(
    app: FastAPI, *, prefix: str = "", names: list[str] | None = None
) -> list[str]:
    """활성 기능의 라우터를 앱에 등록하고 등록된 이름 목록을 반환."""
    registered: list[str] = []
    for feature in load_features(names):
        app.include_router(feature.router, prefix=prefix)
        registered.append(feature.name)
    logger.info("등록된 모듈: %s (prefix=%r)", registered, prefix)
    return registered
