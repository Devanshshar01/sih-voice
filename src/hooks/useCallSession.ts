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
import type {
  AudioMode,
  CallMeta,
  CallPhase,
  CallRiskResponse,
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
  const [serverRiskSnapshot, setServerRiskSnapshot] = useState<CallRiskResponse | null>(null);
  const [liveTranscript, setLiveTranscript] = useState("");

  const wsRef = useRef<WebSocket | null>(null);
  const audioCaptureRef = useRef<LiveAudioCapture | null>(null);
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
    setAnalyser(null);
    wsRef.current?.close();
    wsRef.current = null;
    setWsConnected(false);
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
      setServerRiskSnapshot(null);
      setLiveTranscript("");
      setMuted(false);
      setOnHold(false);
      mutedRef.current = false;
      onHoldRef.current = false;

      try {
        const startRes = await startCall(callerId, recipientId);
        const startedAt = Date.now();
        setMeta({ callId: startRes.call_id, callerId, recipientId, audioMode, startedAt });

        const ws = new WebSocket(buildStreamUrl(startRes.call_id));
        wsRef.current = ws;

        ws.onopen = async () => {
          setWsConnected(true);
          setPhase("active");

          durationIntervalRef.current = window.setInterval(() => {
            setDurationSeconds(Math.floor((Date.now() - startedAt) / 1000));
          }, 1000);

          if (audioMode === "live") {
            try {
              const capture = new LiveAudioCapture();
              audioCaptureRef.current = capture;
              const analyserNode = await capture.start((chunk) => {
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
          setError("Connection to the call stream was interrupted.");
        };

        ws.onclose = () => {
          setWsConnected(false);
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
      const result = await attemptAction(meta.callId, "WIRE_TRANSFER", amount);
      setActionFeedback({ ok: result.ok && result.executed, message: result.message });
      if (actionFeedbackTimeoutRef.current !== null) {
        window.clearTimeout(actionFeedbackTimeoutRef.current);
      }
      actionFeedbackTimeoutRef.current = window.setTimeout(() => setActionFeedback(null), 6000);
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
    serverRiskSnapshot,
    liveTranscript,
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
