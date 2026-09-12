import { useCallback, useEffect, useRef, useState } from "react";
import {
  attemptAction,
  buildStreamUrl,
  fetchRisk,
  requestVerificationCode,
  startCall,
  submitVerificationCode,
  terminateCall,
} from "../lib/api";
import { AUDIO_CHUNK_SAMPLES, LiveAudioCapture, buildDemoFrame } from "../lib/audioCapture";
import { LocalAntiSpoofEngine } from "../lib/localInference";
import { forbidsRawAudioUpload } from "../types";
import type {
  AudioMode,
  CallMeta,
  CallPhase,
  CallRiskResponse,
  LocalRisk,
  RiskTelemetry,
} from "../types";

const DEMO_INTERVAL_MS = Math.round((AUDIO_CHUNK_SAMPLES / 16000) * 1000); // 500ms

interface DemoStage {
  atMs: number;
  transcript: string;
  forceAcousticScore: number;
}

// Mirrors the demonstration script in the prototype blueprint: baseline ->
// acoustic anomaly -> confirmed cloned-voice attack with urgent financial intent.
const CLONED_SCENARIO: DemoStage[] = [
  { atMs: 0, transcript: "Just confirming the numbers on this month's operating expense report before I sign off.", forceAcousticScore: 0.1 },
  { atMs: 5000, transcript: "Sorry, bad line today. Anyway, about that report...", forceAcousticScore: 0.9 },
  { atMs: 9500, transcript: "This is urgent, I need you to process a wire transfer right now, before end of day.", forceAcousticScore: 0.85 },
];

const GENUINE_SCENARIO: DemoStage[] = [
  { atMs: 0, transcript: "Just confirming the numbers on this month's operating expense report before I sign off.", forceAcousticScore: 0.12 },
];

export interface VerificationState {
  demoCode: string | null;
  requestedAt: number | null;
  expiresInSeconds: number;
  input: string;
  submitting: boolean;
  requesting: boolean;
  error: string | null;
}

const initialVerification: VerificationState = {
  demoCode: null,
  requestedAt: null,
  expiresInSeconds: 60,
  input: "",
  submitting: false,
  requesting: false,
  error: null,
};

export interface ActionFeedback {
  ok: boolean;
  message: string;
}

export function useCallSession() {
  const [phase, setPhase] = useState<CallPhase>("idle");
  const [meta, setMeta] = useState<CallMeta | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [wsConnected, setWsConnected] = useState(false);
  const [telemetry, setTelemetry] = useState<RiskTelemetry | null>(null);
  const [telemetryHistory, setTelemetryHistory] = useState<RiskTelemetry[]>([]);
  const [verified, setVerified] = useState(false);
  const [muted, setMuted] = useState(false);
  const [onHold, setOnHold] = useState(false);
  const [durationSeconds, setDurationSeconds] = useState(0);
  const [analyser, setAnalyser] = useState<AnalyserNode | null>(null);
  const [verification, setVerification] = useState<VerificationState>(initialVerification);
  const [actionFeedback, setActionFeedback] = useState<ActionFeedback | null>(null);
  const [actionPending, setActionPending] = useState(false);
  const [serverRiskSnapshot, setServerRiskSnapshot] = useState<CallRiskResponse | null>(null);
  const [liveTranscript, setLiveTranscript] = useState("");
  const [browserOnnxStatus, setBrowserOnnxStatus] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [browserOnnxResult, setBrowserOnnxResult] = useState<{ score: number; label: string } | null>(null);
  const [localRisk, setLocalRisk] = useState<LocalRisk | null>(null);
  const [localModelError, setLocalModelError] = useState<string | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const audioCaptureRef = useRef<LiveAudioCapture | null>(null);
  const localEngineRef = useRef<LocalAntiSpoofEngine | null>(null);
  const demoIntervalRef = useRef<number | null>(null);
  const demoTimeoutsRef = useRef<number[]>([]);
  const durationIntervalRef = useRef<number | null>(null);
  const actionFeedbackTimeoutRef = useRef<number | null>(null);
  const mutedRef = useRef(false);
  const onHoldRef = useRef(false);

  const clearDemoTimers = useCallback(() => {
    if (demoIntervalRef.current !== null) {
      window.clearInterval(demoIntervalRef.current);
      demoIntervalRef.current = null;
    }
    demoTimeoutsRef.current.forEach((id) => window.clearTimeout(id));
    demoTimeoutsRef.current = [];
  }, []);

  const sendWsText = useCallback((payload: Record<string, unknown>) => {
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(payload));
    }
  }, []);

  const runScenario = useCallback(
    (stages: DemoStage[]) => {
      stages.forEach((stage) => {
        const id = window.setTimeout(() => {
          sendWsText({ transcript: stage.transcript, force_acoustic_score: stage.forceAcousticScore });
        }, stage.atMs);
        demoTimeoutsRef.current.push(id);
      });
    },
    [sendWsText]
  );

  const teardown = useCallback(() => {
    clearDemoTimers();
    if (durationIntervalRef.current !== null) {
      window.clearInterval(durationIntervalRef.current);
      durationIntervalRef.current = null;
    }
    audioCaptureRef.current?.stop();
    audioCaptureRef.current = null;
    localEngineRef.current?.dispose();
    localEngineRef.current = null;
    setAnalyser(null);
    wsRef.current?.close();
    wsRef.current = null;
    setWsConnected(false);
    setLocalRisk(null);
    setLocalModelError(null);
    setBrowserOnnxStatus("idle");
    setBrowserOnnxResult(null);
  }, [clearDemoTimers]);

  useEffect(() => teardown, [teardown]);

  const startNewCall = useCallback(
    async (callerId: string, recipientId: string, audioMode: AudioMode) => {
      setError(null);
      setPhase("connecting");
      setTelemetry(null);
      setTelemetryHistory([]);
      setVerified(false);
      setVerification(initialVerification);
      setActionFeedback(null);
      setActionPending(false);
      setServerRiskSnapshot(null);
      setLiveTranscript("");
      setBrowserOnnxStatus("idle");
      setBrowserOnnxResult(null);
      setLocalRisk(null);
      setLocalModelError(null);
      setMuted(false);
      setOnHold(false);
      mutedRef.current = false;
      onHoldRef.current = false;

      // ---- Edge/local mode: derive-only. The call is registered so the
      // dashboard and risk snapshot flow stay intact, but NO raw-audio
      // WebSocket is ever opened and no audio chunk is transmitted. ----
      if (forbidsRawAudioUpload(audioMode)) {
        let callId = "edge-local";
        try {
          const startRes = await startCall(callerId, recipientId);
          callId = startRes.call_id;
        } catch {
          // Fully offline: proceed without a backend call record; only
          // local telemetry exists (capability explicitly degraded).
        }
        const startedAt = Date.now();
        setMeta({ callId, callerId, recipientId, audioMode, startedAt });
        setPhase("active");
        setWsConnected(false);
        wsRef.current = null;

        durationIntervalRef.current = window.setInterval(() => {
          setDurationSeconds(Math.floor((Date.now() - startedAt) / 1000));
        }, 1000);

        const engine = new LocalAntiSpoofEngine();
        localEngineRef.current = engine;
        setBrowserOnnxStatus("loading");
        engine
          .ensureLoaded()
          .then(() => setBrowserOnnxStatus("ready"))
          .catch((loadError: unknown) => {
            setBrowserOnnxStatus("error");
            setLocalModelError(
              loadError instanceof Error ? loadError.message : "Local model failed to load."
            );
          });

        const capture = new LiveAudioCapture();
        audioCaptureRef.current = capture;
        try {
          const analyserNode = await capture.start((chunk) => {
            if (!mutedRef.current && !onHoldRef.current && localEngineRef.current) {
              void localEngineRef.current
                .pushChunk(chunk)
                .then((results) => {
                  const latest = results[results.length - 1];
                  if (!latest) return;
                  const perf = localEngineRef.current?.getPerf();
                  setLocalRisk({
                    acousticScore: latest.score,
                    label: latest.label,
                    modelId: perf?.modelId ?? "unknown",
                    modelLoadMs: perf?.loadMs ?? null,
                    inferenceMs: latest.inferenceMs,
                    p50Ms: perf?.p50Ms ?? null,
                    p95Ms: perf?.p95Ms ?? null,
                    inferenceCount: perf?.inferenceCount ?? 0,
                    heapUsedMb: perf?.heapUsedMb ?? null,
                    windowId: latest.windowId,
                  });
                })
                .catch((inferError: unknown) => {
                  setLocalModelError(
                    inferError instanceof Error ? inferError.message : "Local inference failed."
                  );
                });
            }
          });
          setAnalyser(analyserNode);
        } catch (micError) {
          setError(
            micError instanceof Error
              ? `Microphone access failed: ${micError.message}`
              : "Microphone access failed."
          );
        }
        return;
      }

      try {
        const startRes = await startCall(callerId, recipientId);
        const startedAt = Date.now();
        setMeta({ callId: startRes.call_id, callerId, recipientId, audioMode, startedAt });

        const ws = new WebSocket(buildStreamUrl(startRes.call_id));
        wsRef.current = ws;
        let everOpened = false;

        ws.onopen = async () => {
          everOpened = true;
          setWsConnected(true);
          setPhase("active");

          durationIntervalRef.current = window.setInterval(() => {
            setDurationSeconds(Math.floor((Date.now() - startedAt) / 1000));
          }, 1000);

          if (audioMode === "cloud" || audioMode === "hybrid") {
            try {
              const localEngine =
                audioMode === "hybrid" ? new LocalAntiSpoofEngine() : null;
              if (localEngine) {
                localEngineRef.current = localEngine;
                setBrowserOnnxStatus("loading");
                localEngine
                  .ensureLoaded()
                  .then(() => setBrowserOnnxStatus("ready"))
                  .catch((loadError: unknown) => {
                    setBrowserOnnxStatus("error");
                    setLocalModelError(
                      loadError instanceof Error ? loadError.message : "Local model failed to load."
                    );
                    // Hybrid degrades to cloud semantics on local failure.
                    localEngineRef.current = null;
                  });
              }

              const capture = new LiveAudioCapture();
              audioCaptureRef.current = capture;
              const analyserNode = await capture.start((chunk) => {
                if (localEngineRef.current) {
                  void localEngineRef.current
                    .pushChunk(chunk)
                    .then((results) => {
                      const latest = results[results.length - 1];
                      if (!latest) return;
                      const perf = localEngineRef.current?.getPerf();
                      setBrowserOnnxStatus("ready");
                      setBrowserOnnxResult({ score: latest.score, label: latest.label });
                      setLocalRisk({
                        acousticScore: latest.score,
                        label: latest.label,
                        modelId: perf?.modelId ?? "unknown",
                        modelLoadMs: perf?.loadMs ?? null,
                        inferenceMs: latest.inferenceMs,
                        p50Ms: perf?.p50Ms ?? null,
                        p95Ms: perf?.p95Ms ?? null,
                        inferenceCount: perf?.inferenceCount ?? 0,
                        heapUsedMb: perf?.heapUsedMb ?? null,
                        windowId: latest.windowId,
                      });
                    })
                    .catch((inferError: unknown) => {
                      setLocalModelError(
                        inferError instanceof Error ? inferError.message : "Local inference failed."
                      );
                    });
                }

                // Cloud + hybrid stream raw audio to the backend; edge-local
                // never reaches this branch (guarded above).
                if (!mutedRef.current && !onHoldRef.current && ws.readyState === WebSocket.OPEN) {
                  ws.send(chunk.buffer);
                }
              });
              setAnalyser(analyserNode);
            } catch (micError) {
              setError(
                micError instanceof Error
                  ? `Microphone access failed: ${micError.message}`
                  : "Microphone access failed."
              );
            }
          } else {
            const frame = buildDemoFrame();
            demoIntervalRef.current = window.setInterval(() => {
              if (!mutedRef.current && !onHoldRef.current && ws.readyState === WebSocket.OPEN) {
                ws.send(frame.buffer);
              }
            }, DEMO_INTERVAL_MS);
            runScenario(audioMode === "demo-cloned" ? CLONED_SCENARIO : GENUINE_SCENARIO);
          }
        };

        ws.onmessage = (event) => {
          try {
            const parsed = JSON.parse(event.data) as RiskTelemetry;
            setTelemetry(parsed);
            setTelemetryHistory((prev) => [...prev.slice(-499), parsed]);
          } catch {
            // Ignore malformed frames rather than crash the console mid-call.
          }
        };

        ws.onerror = () => {
          // Browsers never expose the WebSocket failure reason. The usual
          // deployed-frontend causes: backend unreachable, TLS/HTTP mismatch
          // (mixed content), or CORS/origin rejection. State the URL so the
          // operator can act instead of guessing.
          setError(
            `Could not connect to the call stream at ${buildStreamUrl(startRes.call_id)}. ` +
              `Check that the backend is running, that VITE_API_BASE_URL points at it ` +
              `(ws:// vs wss:// must match the page protocol), and that the backend's ` +
              `VOICETRUST_CORS_ORIGINS includes this site's origin.`
          );
        };

        ws.onclose = (event) => {
          setWsConnected(false);
          // A close that never followed a successful open means the connection
          // was refused — ws.onerror already reported the actionable cause; if
          // an active call dropped, say so explicitly.
          if (everOpened && !event.wasClean) {
            setError(`Connection to the call stream was lost (code ${event.code}).`);
          }
        };
      } catch (startError) {
        setError(startError instanceof Error ? startError.message : "Could not start the call.");
        setPhase("idle");
      }
    },
    [runScenario]
  );

  const endCall = useCallback(async () => {
    const callId = meta?.callId;
    teardown();
    setPhase("ended");
    if (callId) {
      try {
        const snapshot = await fetchRisk(callId);
        setServerRiskSnapshot(snapshot);
      } catch {
        // The in-memory session may already be gone; client telemetry history still covers the forensic view.
      }
      void terminateCall(callId);
    }
  }, [meta, teardown]);

  const startOver = useCallback(() => {
    setPhase("idle");
    setMeta(null);
    setError(null);
    setTelemetry(null);
    setTelemetryHistory([]);
    setServerRiskSnapshot(null);
    setDurationSeconds(0);
  }, []);

  const toggleMute = useCallback(() => {
    setMuted((prev) => {
      const next = !prev;
      mutedRef.current = next;
      audioCaptureRef.current?.setMuted(next);
      return next;
    });
  }, []);

  const toggleHold = useCallback(() => {
    setOnHold((prev) => {
      const next = !prev;
      onHoldRef.current = next;
      return next;
    });
  }, []);

  const updateLiveTranscript = useCallback(
    (text: string) => {
      setLiveTranscript(text);
      sendWsText({ transcript: text });
    },
    [sendWsText]
  );

  const requestChallenge = useCallback(async () => {
    if (!meta) return;
    setVerification((prev) => ({ ...prev, requesting: true, error: null }));
    try {
      const res = await requestVerificationCode(meta.callId);
      setVerification((prev) => ({
        ...prev,
        demoCode: res.code,
        requestedAt: Date.now(),
        expiresInSeconds: res.expires_in_seconds,
        requesting: false,
        input: "",
        error: null,
      }));
    } catch (err) {
      setVerification((prev) => ({
        ...prev,
        requesting: false,
        error: err instanceof Error ? err.message : "Could not request a verification code.",
      }));
    }
  }, [meta]);

  const setVerificationInput = useCallback((value: string) => {
    setVerification((prev) => ({ ...prev, input: value, error: null }));
  }, []);

  const submitVerification = useCallback(async () => {
    if (!meta) return;
    setVerification((prev) => ({ ...prev, submitting: true, error: null }));
    try {
      const res = await submitVerificationCode(meta.callId, verification.input);
      if (res.success) {
        setVerified(true);
        setVerification(initialVerification);
      } else {
        setVerification((prev) => ({ ...prev, submitting: false, error: res.message }));
      }
    } catch (err) {
      setVerification((prev) => ({
        ...prev,
        submitting: false,
        error: err instanceof Error ? err.message : "Verification failed.",
      }));
    }
  }, [meta, verification.input]);

  const attemptWireTransfer = useCallback(
    async (amount: number) => {
      if (!meta) return;
      setActionPending(true);
      try {
        const result = await attemptAction(meta.callId, "WIRE_TRANSFER", amount);
        setActionFeedback({ ok: result.ok && result.executed, message: result.message });
        if (actionFeedbackTimeoutRef.current !== null) {
          window.clearTimeout(actionFeedbackTimeoutRef.current);
        }
        actionFeedbackTimeoutRef.current = window.setTimeout(() => setActionFeedback(null), 6000);
      } finally {
        setActionPending(false);
      }
    },
    [meta]
  );

  return {
    phase,
    meta,
    error,
    wsConnected,
    telemetry,
    telemetryHistory,
    verified,
    muted,
    onHold,
    durationSeconds,
    analyser,
    verification,
    actionFeedback,
    actionPending,
    serverRiskSnapshot,
    liveTranscript,
    browserOnnxStatus,
    browserOnnxResult,
    localRisk,
    localModelError,
    startNewCall,
    endCall,
    startOver,
    toggleMute,
    toggleHold,
    updateLiveTranscript,
    requestChallenge,
    setVerificationInput,
    submitVerification,
    attemptWireTransfer,
  };
}

export type UseCallSession = ReturnType<typeof useCallSession>;
