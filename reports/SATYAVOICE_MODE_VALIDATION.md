# SatyaVoice SIH 2026: Cloud / Hybrid / Edge Validation Report

## 1. Objective
Validate the functional behavior, privacy properties, network traffic, and failure/degradation semantics of the three operating modes (Cloud, Hybrid, Edge/Local) to ensure they adhere to Requirement B6.

## 2. Methodology
1. Audited `src/hooks/useCallSession.ts` to trace WebSocket connectivity, microphone graph capture, and raw byte transmission logic for each mode.
2. Verified local ONNX browser model integration and UI fallback behavior.
3. Audited `app/core/risk_engine.py` to confirm handling of missing inputs or remote timeouts (failure degradation).

## 3. Results by Mode

### A. Cloud Mode
- **Architecture**: `LiveAudioCapture` pulls mic input at 16kHz -> sent via WebSocket to Render -> Render queues to HF ZeroGPU.
- **Privacy**: Raw PCM frames are transmitted to the backend over WSS.
- **Degradation / Failure**: If the ZeroGPU Space is unavailable (currently it is rejecting with quota exceeded), the backend's `InferenceProvider` catches the exception and returns a structured `InferenceResult.failure()`. The `risk_engine.py` handles `acoustic_score=None` by falling back to a neutral uninformative score (`0.5`) and marks the telemetry with `degraded: {"anti_spoof": "unavailable"}`. It does NOT assume a best-case "genuine" state silently.

### B. Hybrid Mode
- **Architecture**: A dual-path approach. The browser instantiates `LocalAntiSpoofEngine` and evaluates chunks locally on a Web Worker. SIMULTANEOUSLY, it maintains the WebSocket connection and transmits raw PCM frames to the Render backend for Intent Analysis (ASR) and Speaker Verification.
- **Privacy**: Raw PCM frames **are** transmitted to the backend. Hybrid is about edge computation offload, not strict privacy.
- **Degradation / Failure**: If the local Web Worker ONNX model fails to load or crashes, `useCallSession.ts` sets `localEngineRef.current = null` and degrades seamlessly into Cloud semantics, relying entirely on the WebSocket telemetry from the backend.

### C. Edge / Local Mode
- **Architecture**: The browser runs the `LocalAntiSpoofEngine` exclusively.
- **Privacy**: **VERIFIED PRIVATE**. The `forbidsRawAudioUpload` check in `useCallSession.ts` completely blocks WebSocket instantiation. Although a REST API call `/call/start` is made to provision a session ID (for reporting), `wsRef` is kept null. No raw audio byte array is ever sent across the network.
- **Degradation / Failure**: If the local ONNX model fails to load while in Edge mode, the session becomes incapable of anti-spoof detection. Since there is no backend WebSocket, it cannot fall back to Cloud; it simply reports a UI error (`"Local model failed to load"`).

## 4. Conclusion
The implementation of the three modes conforms exactly to the architectural guarantees. Edge mode provides true data isolation, while Hybrid provides local latency benefits without sacrificing server-side context verification.
