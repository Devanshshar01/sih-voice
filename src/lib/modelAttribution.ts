/**
 * Single source of truth for model attribution shown in the UI (F8).
 *
 * Two DIFFERENT checkpoints exist in this product and must never be blurred:
 *
 *  1. PRODUCTION (server / ZeroGPU): `nii-yamagishilab/mms-300m-anti-deepfake`
 *     — the NII (Yamagishi Lab) MMS-300M SSL checkpoint with an FC head, used
 *     OFF-THE-SHELF. SatyaVoice has NOT fine-tuned it; do not write
 *     "fine-tuned", "Meta", or "custom" anywhere about this model.
 *     Mirrors app/config.py: VOICE_MODEL_ID.
 *
 *  2. OPTIONAL EDGE (browser ONNX): the `public/models/anti_spoof.onnx`
 *     artifact is an export of the Hemgg/Deepfake-audio-detection wav2vec2-base
 *     fine-tune (labels AIVoice/HumanVoice). Mirrors
 *     public/models/anti_spoof.metadata.json: model_id.
 */

export const PROD_ANTISPOOF_MODEL_ID = "nii-yamagishilab/mms-300m-anti-deepfake";
export const PROD_ANTISPOOF_LABEL = "NII MMS-300M Anti-Deepfake (off-the-shelf)";

export const EDGE_ANTISPOOF_MODEL_ID = "Hemgg/Deepfake-audio-detection";
export const EDGE_ANTISPOOF_LABEL = "Wav2Vec2 deepfake classifier (browser ONNX)";

/** Risk-fusion weights — must mirror app/config.py RiskFusionConfig exactly. */
export const RISK_WEIGHTS = {
  acoustic: 0.6,
  intent: 0.3,
  identityMismatch: 0.1,
} as const;

export const weightPercent = (weight: number): string => `${Math.round(weight * 100)}%`;
