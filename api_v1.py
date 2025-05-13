"""
This program is free software: you can redistribute it under the terms
of the GNU General Public License, v. 3.0. If a copy of the GNU General
Public License was not distributed with this file, see <https://www.gnu.org/licenses/>.
"""

import datetime
from typing import Optional, List
from pathlib import Path
from fastapi import APIRouter, HTTPException, Query, Depends, Path as FastAPIPath
from fastapi.responses import FileResponse
from api_schemas import (
    PublicationsRead,
    PublicationsResponse,
    Pagination,
    PlatformIconQuery,
    PlatformManifest,
)
from publications import fetch_publication
from platforms.adapter_manager import AdapterManager
from logutils import get_logger

logger = get_logger(__name__)

router = APIRouter()

ALLOWED_PLATFORM_ICON_EXTENSIONS = ["png", "svg"]
ALLOWED_PLATFORM_MANIFEST_KEYS = [
    "name",
    "shortcode",
    "protocol",
    "service_type",
    "icons_dir",
]


def add_icon_urls(manifest: dict, platform_name: str) -> dict:
    """
    Add icon URLs to the platform manifest if icons are available.

    Args:
        manifest (dict): The platform manifest containing metadata about the platform.
        platform_name (str): The name of the platform.

    Returns:
        dict: The updated platform manifest with icon URLs added, if applicable.
    """
    icons_dir = Path(manifest.pop("icons_dir")).resolve()
    if icons_dir and icons_dir.is_dir():
        for ext in ALLOWED_PLATFORM_ICON_EXTENSIONS:
            icon_path = icons_dir / f"{platform_name}.{ext}"
            if icon_path.is_file():
                manifest[f"{ext}_icon_url"] = (
                    f"/platforms/{platform_name}/icons?ext={ext}"
                )
    return manifest


@router.get("/metrics/publications", response_model=PublicationsResponse)
def get_publication(
    start_date: datetime.date = Query(...),
    end_date: datetime.date = Query(...),
    country_code: Optional[str] = Query(None),
    platform_name: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    gateway_client: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
):
    """Retrieve metrics with optional filters."""
    logger.info(
        f"Fetching metrics with filters: start_date={start_date}, end_date={end_date}, "
        f"country_code={country_code}, platform_name={platform_name}, source={source}, "
        f"status={status}, gateway_client={gateway_client}, page={page}, page_size={page_size}"
    )

    filters = {
        "country_code": country_code,
        "platform_name": platform_name,
        "source": source,
        "status": status,
        "gateway_client": gateway_client,
    }

    try:
        result = fetch_publication(start_date, end_date, filters, page, page_size)
        publications = [
            PublicationsRead(**publication.__data__) for publication in result["data"]
        ]
        total_records = result.get("total_publications", 0)
        total_pages = (total_records + page_size - 1) // page_size
        return PublicationsResponse(
            total_publications=result.get("total_publications", 0),
            total_published=result.get("total_published", 0),
            total_failed=result.get("total_failed", 0),
            data=publications,
            pagination=Pagination(
                total_records=total_records,
                page=page,
                page_size=page_size,
                total_pages=total_pages,
            ),
        )

    except Exception as e:
        logger.error(f"Error fetching publications: {e}")
        raise HTTPException(status_code=500, detail="Error fetching publications")


@router.get("/platforms")
def get_platforms() -> List[PlatformManifest]:
    """
    Retrieve a list of platform adapter manifests.
    """
    AdapterManager._populate_registry()
    platforms = []
    for manifest in AdapterManager._registry.values():
        manifest_copy = {
            key: value
            for key, value in manifest.items()
            if key in ALLOWED_PLATFORM_MANIFEST_KEYS
        }
        platform_name = manifest_copy["name"]
        manifest_copy = add_icon_urls(manifest_copy, platform_name)
        platforms.append(manifest_copy)
    return platforms


@router.get("/platforms/{platform_name}")
def get_platform_data(
    platform_name: str = FastAPIPath(
        ..., description="Platform name", pattern=r"^[a-zA-Z0-9_-]+$"
    )
) -> PlatformManifest:
    """Retrieve the manifest of a platform adapter."""
    AdapterManager._populate_registry()
    adapter = next(
        (
            manifest
            for manifest in AdapterManager._registry.values()
            if manifest["name"].lower() == platform_name.lower()
        ),
        None,
    )
    if not adapter:
        raise HTTPException(status_code=404, detail="Platform not found")

    adapter_copy = {
        key: value
        for key, value in adapter.items()
        if key in ALLOWED_PLATFORM_MANIFEST_KEYS
    }
    adapter_copy = add_icon_urls(adapter_copy, platform_name)
    return adapter_copy


@router.get("/platforms/{platform_name}/icons")
def get_platform_icon(
    query: PlatformIconQuery = Depends(),
    platform_name: str = FastAPIPath(
        ..., description="Platform name", pattern=r"^[a-zA-Z0-9_-]+$"
    ),
) -> FileResponse:
    """
    Retrieve the icon of a platform adapter in the specified format.
    """
    AdapterManager._populate_registry()
    adapter = next(
        (
            manifest
            for manifest in AdapterManager._registry.values()
            if manifest["name"].lower() == platform_name.lower()
        ),
        None,
    )
    if not adapter:
        raise HTTPException(status_code=404, detail="Platform not found")

    icon_name = f"{platform_name}.{query.ext}"
    icons_dir = Path(adapter.get("icons_dir")).resolve()
    icon_path = (icons_dir / icon_name).resolve()

    try:
        icon_path.relative_to(icons_dir)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid icon path") from exc

    if not icon_path.is_file():
        raise HTTPException(status_code=404, detail="Icon not found")

    media_type = "image/svg+xml" if query.ext == "svg" else "image/png"
    return FileResponse(str(icon_path), media_type=media_type)
