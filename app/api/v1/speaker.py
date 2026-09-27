"""Speaker enrollment and matching endpoints (persistent, versioned vault).

Privacy: none of these endpoints ever returns an embedding vector — only
dimensions, versions, counts, and similarities. Raw audio is accepted in the
request body, embedded, and discarded; nothing acoustic is persisted.

F6C: every endpoint requires an authenticated principal (Bearer JWT) —
biometric enrollment/matching is never anonymous. These routes carry no
call/session context, so ownership is not applicable here; per-tenant
isolation is enforced by the vault's tenant_id.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile

from app.core.http_auth import require_authenticated
from app.models.schemas import (
    SpeakerEnrollRequest,
    SpeakerEnrollResponse,
    SpeakerMatchResponse,
)
from app.services.speaker_vault import get_speaker_vault

router = APIRouter(prefix="/speaker", tags=["speaker"])


async def _read_samples(audio_file: UploadFile) -> np.ndarray:
    raw = await audio_file.read()
    if not raw:
        return np.array([], dtype=np.float32)
    try:
        return np.frombuffer(raw, dtype=np.float32)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Audio payload must be float32 PCM bytes.") from exc


@router.post("/enroll", response_model=SpeakerEnrollResponse)
async def enroll_speaker(
    payload: SpeakerEnrollRequest,
    audio_file: UploadFile = File(...),
    authorization: Optional[str] = Header(default=None),
):
    """Create a speaker identity (first sample) or add an enrollment sample.

    Multiple enrollment samples are aggregated into a centroid; the endpoint
    is idempotent for an existing speaker_id.
    """
    require_authenticated(authorization)
    raw = await audio_file.read()
    samples = np.frombuffer(raw, dtype=np.float32) if raw else np.array([], dtype=np.float32)

    vault = get_speaker_vault()
    try:
        enrollment = vault.enroll(
            payload.speaker_id,
            samples,
            tenant_id=payload.tenant_id,
            display_name=payload.display_name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return SpeakerEnrollResponse(**enrollment)


@router.post("/match", response_model=SpeakerMatchResponse)
async def match_speaker(
    audio_file: UploadFile = File(...),
    tenant_id: str = Form("default"),
    speaker_id: str = Form(""),
    authorization: Optional[str] = Header(default=None),
):
    """Verify a live window. Returns similarity/threshold/match + model version."""
    require_authenticated(authorization)
    samples = await _read_samples(audio_file)

    vault = get_speaker_vault()
    result = vault.match(samples, tenant_id=tenant_id, speaker_id=speaker_id or None)
    return SpeakerMatchResponse(**result)


@router.get("/speakers")
async def list_speakers(
    tenant_id: str = "default",
    authorization: Optional[str] = Header(default=None),
):
    """List enrolled identities (metadata only — no embeddings)."""
    require_authenticated(authorization)
    return {"speakers": get_speaker_vault().list_speakers(tenant_id=tenant_id)}


@router.delete("/{speaker_id}")
async def revoke_speaker(
    speaker_id: str,
    tenant_id: str = Form("default"),
    hard: bool = Form(False),
    authorization: Optional[str] = Header(default=None),
):
    """Revoke (soft delete) or erase an enrollment."""
    require_authenticated(authorization)
    vault = get_speaker_vault()
    if not vault.revoke(speaker_id, tenant_id=tenant_id, hard=hard):
        raise HTTPException(status_code=404, detail="Speaker not found.")
    return {"speaker_id": speaker_id, "tenant_id": tenant_id, "deleted": True, "hard": hard}


@router.get("/status")
async def speaker_status(authorization: Optional[str] = Header(default=None)):
    require_authenticated(authorization)
    return get_speaker_vault().state()
