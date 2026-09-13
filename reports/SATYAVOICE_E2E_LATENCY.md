# SatyaVoice SIH 2026: End-to-End Latency Validation Report

## 1. Objective
Validate the end-to-end latency of the SatyaVoice pipeline against the **< 500 ms** SIH 2026 presentation requirement. The specification mandates a decision every 500 ms (via 0.5s hops over 4.0s acoustic windows).

## 2. Methodology & Instrumentation
1. **Local Server-Side Benchmark (`bench_e2e_local.py`)**: Directly instrumented the backend processing stages (Codec, VAD, Anti-Spoof inference, Risk Fusion) in `mock` mode to establish a baseline for server compute time. Measured 200 samples.
2. **WebSocket Round-Trip Benchmark (`bench_ws_roundtrip.py`)**: Measured the actual in-process FastApi `TestClient` WebSocket round-trip for 200 frame submissions, validating the `T2 -> T8` telemetry latency (Render entry to Render exit).
3. **Cloud Endpoint Validation (`hf_zero_gpu/e2e_connectivity_test.py`)**: Attempted end-to-end telemetry through the actual production topology (Render backend -> HF ZeroGPU `infer` API).

## 3. Results: Service-Level Latency (Verified)
The internal core processing (ignoring external network I/O) comfortably exceeds the SIH target.

### Pipeline Stage Breakdown (p95)
* **Codec Normalization:** `0.20 ms`
* **Silero VAD Filter:** `3.79 ms`
* **XLS-R Anti-Spoof (Mock):** `~0.5 ms` 
* **Intent & Risk Fusion:** `1.11 ms`
* **Total In-Process Time:** `~56 ms - 63 ms` (WebSocket round-trip via FastAPI TestClient)

## 4. Results: End-to-End Cloud Latency (UNVERIFIED)
The actual production deployment path relies on Hugging Face ZeroGPU for heavy inference.

**Finding:** End-to-End cloud latency could **NOT** be validated against the < 500 ms requirement because the HF ZeroGPU Space (`devanshshar01-satyavoice-gpu`) is currently rejecting requests with the following error:
> `{"error": "You have exceeded your ZeroGPU runs limit. Authenticate with a Hugging Face token for more quota..."}`

Because the production inference provider is out of quota, the pipeline immediately falls back to its degraded state, failing to provide the true round-trip measurement required for the `< 500 ms` claim.

## 5. Conclusion
- **Internal backend capacity:** PASSED (< 100 ms overhead).
- **Production E2E constraint (< 500 ms):** FAILED TO VERIFY due to infrastructure quota limits. Do not claim this metric in presentation without resolving the Hugging Face API limits and remeasuring.
