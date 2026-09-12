/**
 * SatyaVoice local anti-spoof inference worker.
 *
 * Runs the ONNX anti-spoof model OFF the UI thread via onnxruntime-web.
 * Protocol (postMessage):
 *
 *   -> { type: "load",  modelUrl, metadataUrl }   (idempotent; caches)
 *   -> { type: "infer", windowId, samples: Float32Array }
 *   <- { type: "loading" }
 *   <- { type: "ready", loadMs, modelId, sampleRate, labels }
 *   <- { type: "result", windowId, score, label, inferenceMs }
 *   <- { type: "error", stage: "load" | "infer", message, windowId? }
 *
 * Model files are fetched once and cached by the HTTP cache + the session
 * promise inside this worker, so repeated loads never re-download.
 */

let sessionPromise = null;
let sessionMeta = null;

async function loadSession(modelUrl, metadataUrl) {
  if (sessionPromise) return sessionPromise;
  sessionPromise = (async () => {
    const t0 = performance.now();
    const [ort, metadataResponse] = await Promise.all([
      import("onnxruntime-web"),
      fetch(metadataUrl).then((r) => {
        if (!r.ok) throw new Error(`Metadata fetch failed (${r.status})`);
        return r.json();
      }),
    ]);

    const session = await ort.InferenceSession.create(modelUrl, {
      executionProviders: ["wasm"],
      graphOptimizationLevel: "all",
    });
    const loadMs = performance.now() - t0;
    sessionMeta = { ort, session, metadata: metadataResponse };
    return { loadMs, metadata: metadataResponse };
  })();
  // On failure, allow a retry on the next "load" message instead of caching
  // the broken promise forever.
  sessionPromise.catch(() => {
    sessionPromise = null;
    sessionMeta = null;
  });
  return sessionPromise;
}

function softmax(values) {
  const max = Math.max(...Array.from(values));
  const exps = new Float32Array(values.length);
  let denom = 0;
  for (let i = 0; i < values.length; i += 1) {
    exps[i] = Math.exp(values[i] - max);
    denom += exps[i];
  }
  for (let i = 0; i < exps.length; i += 1) exps[i] /= denom;
  return exps;
}

self.onmessage = async (event) => {
  const msg = event.data;
  try {
    if (msg.type === "load") {
      self.postMessage({ type: "loading" });
      const { loadMs, metadata } = await loadSession(msg.modelUrl, msg.metadataUrl);
      self.postMessage({
        type: "ready",
        loadMs,
        modelId: metadata.model_id,
        sampleRate: metadata.sample_rate,
        labels: metadata.labels,
      });
      return;
    }

    if (msg.type === "infer") {
      if (!sessionMeta) {
        // Auto-load on first inference (idempotent if already loading).
        await loadSession(msg.modelUrl, msg.metadataUrl);
      }
      const { ort, session, metadata } = sessionMeta;
      const t0 = performance.now();
      const sample =
        msg.samples instanceof Float32Array && msg.samples.length > 0
          ? msg.samples
          : new Float32Array(metadata.sample_rate || 16000);
      const tensor = new ort.Tensor("float32", sample, [1, sample.length]);
      const output = await session.run({ input_values: tensor });
      const logits = output.logits.data;
      const probs = softmax(logits);
      const syntheticIndex = metadata.synthetic_index ?? probs.indexOf(Math.max(...Array.from(probs)));
      const score = Number(probs[syntheticIndex] ?? 0);
      const label = metadata.labels[String(syntheticIndex)] ?? "unknown";
      self.postMessage({
        type: "result",
        windowId: msg.windowId,
        score,
        label,
        inferenceMs: performance.now() - t0,
      });
      return;
    }
  } catch (err) {
    self.postMessage({
      type: "error",
      stage: msg.type === "infer" && sessionMeta ? "infer" : "load",
      message: err && err.message ? err.message : String(err),
      windowId: msg.windowId,
    });
  }
};
