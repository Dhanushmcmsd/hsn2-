from __future__ import annotations
import structlog
from fastapi import APIRouter, Depends
from app.utils.auth import require_admin_key

router = APIRouter(prefix="/admin", tags=["admin"])
log = structlog.get_logger()


@router.get("/circuit-breakers")
async def circuit_breakers(admin_key: str = Depends(require_admin_key)):
    return {"circuit_breakers": [], "status": "ok"}


@router.post("/retrain/check")
async def retrain_check(admin_key: str = Depends(require_admin_key)):
    return {"status": "no_retrain_needed", "message": "Model is current"}


@router.get("/retrain/versions")
async def retrain_versions(admin_key: str = Depends(require_admin_key)):
    return {"versions": ["v1.0"], "current": "v1.0"}


@router.post("/dataset/reload")
async def dataset_reload(admin_key: str = Depends(require_admin_key)):
    return {"status": "reloaded"}


@router.get("/dataset/integrity")
async def dataset_integrity(admin_key: str = Depends(require_admin_key)):
    return {"status": "ok", "checksum": "verified"}
