import * as ort from "onnxruntime-web";

export type BrowserInferenceStatus = "idle" | "loading" | "ready" | "error";

interface LoadedAntiSpoofModel {
  session: ort.InferenceSession;
  metadata: {
    sample_rate: number;
    labels: Record<string, string>;
    synthetic_index?: number;
  };
}

let loadedModelPromise: Promise<LoadedAntiSpoofModel> | null = null;

export async function loadAntiSpoofOnnxModel(): Promise<LoadedAntiSpoofModel> {
  if (!loadedModelPromise) {
    loadedModelPromise = (async () => {
      const [session, metadataResponse] = await Promise.all([
        ort.InferenceSession.create("/models/anti_spoof.onnx", {
          executionProviders: ["wasm"],
          graphOptimizationLevel: "all",
        }),
        fetch("/models/anti_spoof.metadata.json").then((response) => {
          if (!response.ok) {
            throw new Error("Failed to load anti-spoof ONNX metadata.");
          }
          return response.json() as Promise<{
            sample_rate: number;
            labels: Record<string, string>;
            synthetic_index?: number;
          }>;
        }),
      ]);

      return {
        session,
        metadata: metadataResponse,
      };
    })();
  }

  return loadedModelPromise;
}

function softmax(values: Float32Array): Float32Array {
  const max = Math.max(...Array.from(values));
  const exps = new Float32Array(values.length);
  let denom = 0;

  for (let i = 0; i < values.length; i += 1) {
    const exponent = Math.exp(values[i] - max);
    exps[i] = exponent;
    denom += exponent;
  }

  for (let i = 0; i < exps.length; i += 1) {
    exps[i] /= denom;
  }

  return exps;
}

export async function runAntiSpoofOnnxSample(audioWindow: Float32Array): Promise<{ score: number; label: string; }> {
  const { session, metadata } = await loadAntiSpoofOnnxModel();

  const sample = audioWindow.length > 0 ? audioWindow : new Float32Array(metadata.sample_rate || 16000);
  const tensor = new ort.Tensor("float32", sample, [1, sample.length]);
  const output = await session.run({ input_values: tensor });
  const logits = output.logits.data as Float32Array;
  const probabilities = softmax(logits);

  const syntheticIndex = metadata.synthetic_index ?? probabilities.indexOf(Math.max(...Array.from(probabilities)));
  const score = Number(probabilities[syntheticIndex] ?? 0);
  const label = metadata.labels[String(syntheticIndex)] ?? "unknown";

  return {
    score,
    label,
  };
}
