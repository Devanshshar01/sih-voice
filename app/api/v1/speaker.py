"""Speaker enrollment and matching endpoints (persistent, versioned vault).

Privacy: none of these endpoints ever returns an embedding vector — only
dimensions, versions, counts, and similarities. Raw audio is accepted in the
request body, embedded, and discarded; nothing acoustic is persisted.

Security: every route requires an API key in production; the operating tenant
is derived from the key, never from client input, so one tenant cannot touch
another's enrollments. In development/demo (no keys configured) routes are
open under the shared "default" tenant.
"""
from __future__ import annotations

import numpy as np
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app import config
from app.core.auth import AuthContext, require_auth
from app.models.schemas import SpeakerEnrollResponse, SpeakerMatchResponse
from app.services.speaker_vault import get_speaker_vault

router = APIRouter(prefix="/speaker", tags=["speaker"])


async def _read_samples(audio_file: UploadFile) -> np.ndarray:
    raw = await audio_file.read()
    if not raw:
        return np.array([], dtype=np.float32)
    if len(raw) > config.MAX_AUDIO_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Audio payload exceeds the configured size limit.")
    try:
        return np.frombuffer(raw, dtype=np.float32)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Audio payload must be float32 PCM bytes.") from exc


@router.post("/enroll", response_model=SpeakerEnrollResponse)
async def enroll_speaker(
    audio_file: UploadFile = File(...),
    speaker_id: str = Form(...),
    tenant_id: str = Form("default"),
    display_name: str = Form(""),
    auth: AuthContext = Depends(require_auth),
):
    """Create a speaker identity (first sample) or add an enrollment sample.

    Multipart form fields (speaker_id required). Multiple enrollment samples
    are aggregated into a centroid; the endpoint is idempotent per speaker_id.
    """
    # Tenant boundary: a client may only enroll into its OWN tenant. The
    # legacy ``tenant_id`` field is accepted but must MATCH the key's tenant —
    # cross-tenant enrollment is a hard 403.
    requested_tenant = tenant_id or "default"
    if auth.tenant_id != "default" and requested_tenant != auth.tenant_id:
        raise HTTPException(status_code=403, detail="Cross-tenant enrollment is not permitted.")

    raw = await audio_file.read()
    if len(raw) > config.MAX_AUDIO_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Audio payload exceeds the configured size limit.")
    samples = np.frombuffer(raw, dtype=np.float32) if raw else np.array([], dtype=np.float32)

    vault = get_speaker_vault()
    try:
        enrollment = vault.enroll(
            speaker_id,
            samples,
            tenant_id=auth.tenant_id,
            display_name=display_name or None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return SpeakerEnrollResponse(**enrollment)


@router.post("/match", response_model=SpeakerMatchResponse)
async def match_speaker(
    audio_file: UploadFile = File(...),
    speaker_id: str = Form(""),
    auth: AuthContext = Depends(require_auth),
):
    """Verify a live window. Returns similarity/threshold/match + model version."""
    samples = await _read_samples(audio_file)

    vault = get_speaker_vault()
    result = vault.match(samples, tenant_id=auth.tenant_id, speaker_id=speaker_id or None)
    return SpeakerMatchResponse(**result)


@router.get("/speakers")
async def list_speakers(auth: AuthContext = Depends(require_auth)):
    """List enrolled identities (metadata only — no embeddings)."""
    return {"speakers": get_speaker_vault().list_speakers(tenant_id=auth.tenant_id)}


@router.delete("/{speaker_id}")
async def revoke_speaker(
    speaker_id: str,
    hard: bool = Form(False),
    auth: AuthContext = Depends(require_auth),
):
    """Revoke (soft delete) or erase an enrollment."""
    vault = get_speaker_vault()
    if not vault.revoke(speaker_id, tenant_id=auth.tenant_id, hard=hard):
        raise HTTPException(status_code=404, detail="Speaker not found.")
    return {"speaker_id": speaker_id, "tenant_id": auth.tenant_id, "deleted": True, "hard": hard}


@router.get("/status")
async def speaker_status(auth: AuthContext = Depends(require_auth)):
    return get_speaker_vault().state()
