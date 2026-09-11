/**
 * Local anti-spoof host: owns the inference worker, canonical 4s/0.5s
 * windowing (mirroring app/config.py), and performance telemetry.
 *
 * The worker is the only place raw audio meets the ONNX model; this host
 * never exposes samples beyond the worker boundary.
 */
import { AUDIO_CHUNK_SAMPLES, AUDIO_SAMPLE_RATE } from "./audioCapture";

export const WINDOW_SAMPLES = 64000; // 4.0 s @ 16 kHz (canonical SIH window)
export const HOP_SAMPLES = 8000; // 0.5 s @ 16 kHz (canonical SIH hop)

export type LocalModelStatus = "idle" | "loading" | "ready" | "error";

export interface LocalInferenceResult {
  windowId: number;
  score: number;
  label: string;
  inferenceMs: number;
}

export interface LocalModelPerf {
  loadMs: number | null;
  modelId: string | null;
  lastInferenceMs: number | null;
  inferenceCount: number;
  p50Ms: number | null;
  p95Ms: number | null;
  heapUsedMb: number | null; // null where performance.memory is unsupported
}

type Pending = {
  resolve: (r: LocalInferenceResult) => void;
  reject: (e: Error) => void;
};

export class LocalAntiSpoofEngine {
  private worker: Worker | null = null;
  private status: LocalModelStatus = "idle";
  private loadPromise: Promise<void> | null = null;
  private pendingInferences = new Map<number, Pending>();
  private nextWindowId = 1;
  private errors: string | null = null;
  private inferenceTimes: number[] = [];
  private loadMs: number | null = null;
  private modelId: string | null = null;
  private lastInferenceMs: number | null = null;

  private readonly modelUrl = "/models/anti_spoof.onnx";
  private readonly metadataUrl = "/models/anti_spoof.metadata.json";

  getStatus(): LocalModelStatus {
    return this.status;
  }

  getError(): string | null {
    return this.errors;
  }

  getPerf(): LocalModelPerf {
    const times = [...this.inferenceTimes].sort((a, b) => a - b);
    const pick = (q: number) =>
      times.length ? Number(times[Math.min(times.length - 1, Math.floor(q * times.length))]) : null;
    const mem = (performance as unknown as { memory?: { usedJSHeapSize: number } }).memory;
    return {
      loadMs: this.loadMs,
      modelId: this.modelId,
      lastInferenceMs: this.lastInferenceMs,
      inferenceCount: this.inferenceTimes.length,
      p50Ms: pick(0.5),
      p95Ms: pick(0.95),
      heapUsedMb: mem ? Number((mem.usedJSHeapSize / (1024 * 1024)).toFixed(1)) : null,
    };
  }

  /** Idempotent, lazy, failure-retryable model load. */
  ensureLoaded(): Promise<void> {
    if (this.status === "ready") return Promise.resolve();
    if (this.status === "loading" && this.loadPromise) return this.loadPromise;

    this.status = "loading";
    this.loadPromise = this.withWorker(async (worker) => {
      await new Promise<void>((resolve, reject) => {
        const onLoadMessage = (event: MessageEvent) => {
          const msg = event.data;
          if (msg.type === "ready") {
            this.loadMs = msg.loadMs;
            this.modelId = msg.modelId;
            this.status = "ready";
            worker.removeEventListener("message", onLoadMessage);
            resolve();
          } else if (msg.type === "error" && msg.stage === "load") {
            this.status = "error";
            this.errors = msg.message;
            worker.removeEventListener("message", onLoadMessage);
            reject(new Error(`Model load failed: ${msg.message}`));
          }
        };
        worker.addEventListener("message", onLoadMessage);
        worker.postMessage({ type: "load", modelUrl: this.modelUrl, metadataUrl: this.metadataUrl });
      });
    }).finally(() => {
      this.loadPromise = null;
    });

    return this.loadPromise;
  }

  /**
   * Feed a 0.5 s capture chunk. Windows are emitted on the canonical
   * 4 s window / 0.5 s hop contract. Returns results for windows completed
   * by this chunk (normally 0 or 1).
   */
  async pushChunk(chunk: Float32Array): Promise<LocalInferenceResult[]> {
    if (!this.ring) {
      this.ring = new Float32Array(WINDOW_SAMPLES);
    }
    const results: LocalInferenceResult[] = [];
    let offset = 0;
    while (offset < chunk.length) {
      const take = Math.min(chunk.length - offset, WINDOW_SAMPLES - this.filled);
      this.ring.set(chunk.subarray(offset, offset + take), this.filled);
      this.filled += take;
      offset += take;

      if (this.filled === WINDOW_SAMPLES) {
        const windowId = this.nextWindowId++;
        const windowCopy = this.ring.slice(0);
        // Advance one hop: keep the tail 3.5 s, next chunk refills 0.5 s.
        this.ring.copyWithin(0, HOP_SAMPLES);
        this.filled = WINDOW_SAMPLES - HOP_SAMPLES;
        results.push(await this.runInference(windowId, windowCopy));
      }
    }
    return results;
  }

  async runInference(windowId: number, samples: Float32Array): Promise<LocalInferenceResult> {
    await this.ensureLoaded();
    return this.withWorker(
      (worker) =>
        new Promise<LocalInferenceResult>((resolve, reject) => {
          this.pendingInferences.set(windowId, { resolve, reject });
          worker.postMessage({ type: "infer", windowId, samples, modelUrl: this.modelUrl, metadataUrl: this.metadataUrl });
        })
    );
  }

  reset(): void {
    this.filled = 0;
    // Keep the loaded model (expensive); drop only window state + metrics
    // from the previous call.
    this.inferenceTimes = [];
    this.lastInferenceMs = null;
  }

  dispose(): void {
    if (this.worker) {
      this.worker.terminate();
      this.worker = null;
    }
    this.workerReady = null;
    this.status = "idle";
    this.loadPromise = null;
    this.pendingInferences.clear();
    this.ring = null;
    this.filled = 0;
    this.inferenceTimes = [];
    this.loadMs = null;
    this.modelId = null;
    this.lastInferenceMs = null;
    this.errors = null;
  }

  // ------------------------------------------------------------------
  private ring: Float32Array | null = null;
  private filled = 0;
  private workerReady: Promise<Worker> | null = null;

  private withWorker<T>(fn: (worker: Worker) => Promise<T>): Promise<T> {
    if (!this.workerReady) {
      this.workerReady = Promise.resolve(new Worker("/onnx-worker.js")).then((worker) => {
        this.worker = worker;
        worker.onmessage = (event: MessageEvent) => {
          const msg = event.data;
          if (msg.type === "result") {
            const pending = this.pendingInferences.get(msg.windowId);
            if (pending) {
              this.pendingInferences.delete(msg.windowId);
              this.inferenceTimes.push(msg.inferenceMs);
              this.lastInferenceMs = msg.inferenceMs;
              pending.resolve({
                windowId: msg.windowId,
                score: msg.score,
                label: msg.label,
                inferenceMs: msg.inferenceMs,
              });
            }
          } else if (msg.type === "error" && msg.stage === "infer") {
            const pending = this.pendingInferences.get(msg.windowId);
            if (pending) {
              this.pendingInferences.delete(msg.windowId);
              pending.reject(new Error(msg.message));
            }
          }
        };
        worker.onerror = (event) => {
          // Surface worker-level failures (script load error, etc.).
          const err = new Error(event.message || "Worker failed");
          this.pendingInferences.forEach((p) => p.reject(err));
          this.pendingInferences.clear();
          if (this.status === "loading") {
            this.status = "error";
            this.errors = err.message;
            this.loadPromise = null;
          }
        };
        return worker;
      });
    }
    return this.workerReady.then(fn);
  }
}

export { AUDIO_SAMPLE_RATE, AUDIO_CHUNK_SAMPLES };
