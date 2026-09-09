"""Speaker enrollment and matching endpoints for Phase 3."""
from __future__ import annotations

import numpy as np
from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.models.schemas import SpeakerEnrollRequest, SpeakerEnrollResponse, SpeakerMatchResponse
from app.services.speaker_vault import get_speaker_vault

router = APIRouter(prefix="/speaker", tags=["speaker"])


@router.post("/enroll", response_model=SpeakerEnrollResponse)
async def enroll_speaker(
    payload: SpeakerEnrollRequest,
    audio_file: UploadFile = File(...),
):
    raw = await audio_file.read()
    samples = np.frombuffer(raw, dtype=np.float32) if raw else np.array([], dtype=np.float32)

    vault = get_speaker_vault()
    try:
        enrollment = vault.enroll(payload.speaker_id, samples)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return SpeakerEnrollResponse(**enrollment)


@router.post("/match", response_model=SpeakerMatchResponse)
async def match_speaker(audio_file: UploadFile = File(...)):
    raw = await audio_file.read()
    samples = np.frombuffer(raw, dtype=np.float32) if raw else np.array([], dtype=np.float32)

    vault = get_speaker_vault()
    return SpeakerMatchResponse(**vault.match(samples))


@router.get("/status")
async def speaker_status():
    return get_speaker_vault().state()
