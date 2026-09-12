import type { UseCallSession } from "../hooks/useCallSession";
import TrustGauge from "./TrustGauge";
import Spectrograph from "./Spectrograph";
import StatusBanner from "./StatusBanner";
import ThreatBreakdown from "./ThreatBreakdown";
import WireTransferPanel from "./WireTransferPanel";
import CallControls from "./CallControls";
import VerificationModal from "./VerificationModal";
import RiskTimeline, { statusLabel } from "./RiskTimeline";

interface CallDashboardProps {
  session: UseCallSession;
}

function Metric({ label, value, detail, tone = "text-paper" }: { label: string; value: string; detail: string; tone?: string }) {
  return (
    <div className="surface p-4">
      <p className="section-label">{label}</p>
      <p className={`mt-2 text-2xl font-semibold tracking-tight ${tone}`}>{value}</p>
      <p className="mt-1 text-xs leading-relaxed text-mute">{detail}</p>
    </div>
  );
}

export default function CallDashboard({ session }: CallDashboardProps) {
  const {
    meta, telemetry, telemetryHistory, muted, onHold, analyser, verified, verification,
    actionFeedback, actionPending, liveTranscript, browserOnnxStatus, browserOnnxResult,
    localRisk, localModelError,
    endCall, toggleMute, toggleHold, updateLiveTranscript, requestChallenge,
    setVerificationInput, submitVerification, attemptWireTransfer,
  } = session;

  const status = telemetry?.status ?? "ALLOW";
  const score = telemetry?.risk_score ?? 0;
  const acousticScore = telemetry?.acoustic_score ?? 0;
  const intentScore = telemetry?.intent_score ?? 0;
  const rationale = telemetry?.rationale ?? [];
  const identityMismatch = telemetry?.identity_mismatch ?? null;
  const speakerSimilarity = telemetry?.speaker_score ?? null;
  const intentRisks = telemetry?.intent_risks ?? [];
  const detectedLanguage = telemetry?.detected_language ?? null;
  const languageLabel =
    detectedLanguage == null
      ? null
      : detectedLanguage === "en"
        ? "English"
        : detectedLanguage === "hi"
          ? "Hindi"
          : detectedLanguage === "ta"
            ? "Tamil"
            : detectedLanguage === "te"
              ? "Telugu"
              : detectedLanguage === "bn"
                ? "Bengali"
                : detectedLanguage === "mr"
                  ? "Marathi"
                  : detectedLanguage;
  const showVerification = status === "LOCK_VERIFY" && !verified;
  const browserOnnxPercent = browserOnnxResult ? Math.round(browserOnnxResult.score * 100) : null;
  const currentStatus = verified ? "SAFE" : statusLabel(status);
  const statusTone = currentStatus === "LOCKED" ? "text-danger" : currentStatus === "SUSPICIOUS" ? "text-warn" : "text-safe";
  const actionState = actionPending ? "PROCESSING" : actionFeedback ? (actionFeedback.ok ? "EXECUTED" : "BLOCKED") : showVerification ? "AWAITING VERIFICATION" : "READY";

  return (
    <div className="console-grid flex min-h-0 flex-1 flex-col">
      <main className="min-h-0 flex-1 overflow-y-auto px-4 py-5 sm:px-6 sm:py-7 lg:px-8">
        <div className="mx-auto max-w-[1440px]">
          <div className="mb-5 flex flex-col gap-3 border-b border-ink-700 pb-4 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <p className="eyebrow">Active call / real-time risk operations</p>
              <h1 className="mt-1 text-2xl font-semibold tracking-tight text-paper sm:text-3xl">Voice integrity monitor</h1>
              <p className="mt-2 max-w-2xl text-sm leading-relaxed text-paper-dim">Every decision is grounded in the acoustic signal, observed intent, and the evidence currently available in this session.</p>
            </div>
            <div className="flex items-center gap-2 text-left text-xs text-mute sm:text-right">
              <span className="h-1.5 w-1.5 rounded-full bg-safe shadow-[0_0_8px_theme(colors.safe.DEFAULT)]" />
              <div><p className="font-mono text-paper">{meta?.callId ?? "CONNECTING"}</p><p className="mt-1">{meta && !meta.audioMode.startsWith("demo") ? "LIVE MICROPHONE" : "CONTROLLED SCENARIO"}</p></div>
            </div>
          </div>

          <StatusBanner status={verified ? "ALLOW" : status} rationale={rationale} verified={verified} />

          <div className="mt-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Metric label="Overall risk" value={`${Math.round(score * 100)}%`} detail="Fused session risk score" tone={statusTone} />
            <Metric label="Risk status" value={currentStatus} detail={verified ? "Verification override active" : "Current policy decision"} tone={statusTone} />
            <Metric label="Acoustic anti-spoof" value={`${Math.round(acousticScore * 100)}%`} detail="Synthetic voice likelihood" tone={acousticScore > 0.7 ? "text-danger" : "text-paper"} />
            <Metric label="Intent pressure" value={`${Math.round(intentScore * 100)}%`} detail="Urgency / sensitive-request signal" tone={intentScore > 0.7 ? "text-danger" : "text-paper"} />
          </div>

          <div className="mt-5 grid grid-cols-1 gap-5 xl:grid-cols-[minmax(0,1.35fr)_minmax(360px,0.65fr)]">
            <div className="space-y-5">
              <section className="panel p-5 sm:p-6">
                <div className="flex flex-wrap items-start justify-between gap-4">
                  <div>
                    <p className="eyebrow">Primary decision surface</p>
                    <h2 className="mt-1 text-lg font-medium text-paper">Why this call is {currentStatus.toLowerCase()}</h2>
                  </div>
                  <div className="text-right"><span className={`font-mono text-3xl font-semibold ${statusTone}`}>{Math.round(score * 100)}</span><span className="ml-1 text-xs text-mute">/ 100</span></div>
                </div>
                <div className="mt-5 grid gap-5 md:grid-cols-[180px_minmax(0,1fr)] md:items-center">
                  <div className="flex justify-center">{telemetry ? <TrustGauge score={score} status={status} /> : <p className="py-10 text-sm text-mute">Calibrating…</p>}</div>
                  <div className="space-y-3">
                    {rationale.length > 0 ? rationale.map((line) => <div key={line} className="border-l-2 border-danger bg-ink-900/60 px-3 py-2 text-sm leading-relaxed text-paper-dim">{line}</div>) : <p className="text-sm text-mute">No elevated rationale signals have been reported yet.</p>}
                  </div>
                </div>
              </section>

              <section className="surface p-5 sm:p-6">
                <div className="mb-4 flex items-start justify-between gap-3"><div><p className="eyebrow">Audio telemetry</p><h2 className="mt-1 text-sm font-medium text-paper">Live spectrogram / waveform</h2></div><span className="font-mono text-[10px] text-mute">16 kHz · mono</span></div>
                <Spectrograph analyser={analyser} status={status} />
              </section>

              <RiskTimeline points={telemetryHistory} />

              <section className="surface p-5 sm:p-6">
                <div className="flex items-start justify-between gap-3"><div><p className="eyebrow">Conversation context</p><h2 className="mt-1 text-sm font-medium text-paper">ASR transcript</h2></div><span className="font-mono text-[10px] text-mute">{meta && !meta.audioMode.startsWith("demo") ? "MANUAL ASR INPUT" : "NOT EXPOSED"}</span></div>
                {meta && !meta.audioMode.startsWith("demo") ? (
                  <div>
                    <textarea id="live-transcript" value={liveTranscript} onChange={(e) => updateLiveTranscript(e.target.value)} rows={3} placeholder="Type what the caller is asking for, as it happens…" className="field-input mt-4 w-full resize-none font-sans" />
                    {languageLabel && <p className="mt-2 text-xs text-mute">Language: <span className="font-medium text-paper">{languageLabel}</span></p>}
                    {intentRisks.length > 0 && (
                      <div className="mt-3 space-y-2">
                        {intentRisks.map((risk, i) => (
                          <div key={`${risk.category}-${risk.matched_phrase}-${i}`} className="border border-ink-700 bg-ink-900/60 px-3 py-2">
                            <div className="flex items-center justify-between gap-2">
                              <span className={`text-xs font-semibold uppercase tracking-wide ${risk.severity === "critical" ? "text-danger" : risk.severity === "elevated" ? "text-warn" : "text-mute"}`}>
                                {risk.category} · {risk.speech_act}
                              </span>
                              <span className="font-mono text-[11px] text-mute">{risk.language}</span>
                            </div>
                            <p className="mt-1 text-sm text-paper-dim">“{risk.matched_phrase}” — {risk.evidence}</p>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                ) : <p className="mt-4 border border-ink-700 bg-ink-900/60 p-3 text-sm leading-relaxed text-mute">Transcript data is not exposed for this audio mode. The dashboard is showing only server telemetry and rationale signals.</p>}
              </section>

              {(meta?.audioMode === "hybrid" || meta?.audioMode === "edge-local") && (
                <section className="surface p-5 sm:p-6">
                  <p className="eyebrow">Local anti-spoof (in-browser)</p>
                  <h2 className="mt-1 text-sm font-medium text-paper">On-device inference</h2>
                  <p className="mt-3 max-w-2xl text-sm leading-relaxed text-paper-dim">
                    {meta?.audioMode === "edge-local"
                      ? "Raw audio never leaves this device. Only derived scores are produced locally — ASR, speaker matching, and policy fusion are unavailable and shown as degraded."
                      : "Anti-spoof runs in this browser; the backend still performs ASR, speaker matching, and policy fusion."}
                  </p>
                  <p className="mt-3 font-mono text-xs text-signal">
                    {browserOnnxStatus === "loading" ? "MODEL LOADING…" : browserOnnxStatus === "ready" && browserOnnxResult ? `LIKELIHOOD ${browserOnnxPercent}% · ${browserOnnxResult.label}${localRisk ? ` · MODEL ${localRisk.modelId} · LOAD ${localRisk.modelLoadMs ? Math.round(localRisk.modelLoadMs) : "—"}MS · INFER ${Math.round(localRisk.inferenceMs)}MS (P50 ${localRisk.p50Ms ? Math.round(localRisk.p50Ms) : "—"} / P95 ${localRisk.p95Ms ? Math.round(localRisk.p95Ms) : "—"}) · N=${localRisk.inferenceCount}${localRisk.heapUsedMb != null ? ` · HEAP ${localRisk.heapUsedMb}MB` : ""}` : ""}` : browserOnnxStatus === "error" ? `MODEL ERROR: ${localModelError ?? "unknown"} — hybrid continues on the backend stream; edge mode is degraded.` : "WAITING FOR AUDIO"}
                  </p>
                  {meta?.audioMode === "edge-local" && (
                    <p className="mt-3 border border-warn/40 bg-warn-bg px-3 py-2 text-xs text-warn">
                      Degraded (offline): conversation transcript, speaker identity, and policy fusion require the cloud pipeline and are intentionally unavailable — raw audio is never uploaded in this mode.
                    </p>
                  )}
                </section>
              )}
            </div>

            <div className="space-y-5">
              <section className="panel p-4 sm:p-5"><p className="eyebrow">Identity controls</p><h2 className="mt-1 text-sm font-medium text-paper">Verification posture</h2><div className="mt-4 space-y-3"><div className="flex items-center justify-between border-b border-ink-700 pb-3 text-sm"><span className="text-mute">Speaker similarity</span><span className="font-mono text-mute">{speakerSimilarity != null ? `${Math.round(speakerSimilarity * 100)}%` : "UNKNOWN (NO REFERENCE)"}</span></div><div className="flex items-center justify-between border-b border-ink-700 pb-3 text-sm"><span className="text-mute">Identity mismatch</span><span className="font-mono text-mute">{identityMismatch != null ? `${Math.round(identityMismatch * 100)}%` : "NEUTRAL"}</span></div><div className="flex items-center justify-between text-sm"><span className="text-mute">Challenge state</span><span className={`font-mono ${verified ? "text-safe" : showVerification ? "text-danger" : "text-paper"}`}>{verified ? "VERIFIED" : showVerification ? "REQUIRED" : "NOT REQUIRED"}</span></div></div></section>
              <ThreatBreakdown acousticScore={acousticScore} intentScore={intentScore} identityMismatch={identityMismatch} speakerSimilarity={speakerSimilarity} rationale={rationale} status={status} />
              <section className="panel p-4 sm:p-5"><div className="flex items-start justify-between gap-3"><div><p className="eyebrow">Protected action</p><h2 className="mt-1 text-sm font-medium text-paper">Current action state</h2></div><span className={`font-mono text-[10px] ${actionState === "BLOCKED" || actionState === "AWAITING VERIFICATION" ? "text-danger" : actionState === "EXECUTED" ? "text-safe" : "text-signal"}`}>{actionState}</span></div><p className="mt-4 text-sm leading-relaxed text-paper-dim">Wire transfer requests remain gated until the current identity and intent signals satisfy policy.</p></section>
              <WireTransferPanel locked={showVerification} feedback={actionFeedback} pending={actionPending} onAttempt={attemptWireTransfer} />
            </div>
          </div>
        </div>
      </main>
      <div className="shrink-0 border-t border-ink-700 bg-ink-900/95 px-4 py-3 backdrop-blur-sm sm:px-6"><div className="mx-auto max-w-[1440px]"><CallControls muted={muted} onHold={onHold} onToggleMute={toggleMute} onToggleHold={toggleHold} onEndCall={endCall} /></div></div>
      {showVerification && <VerificationModal verification={verification} onRequestCode={requestChallenge} onInputChange={setVerificationInput} onSubmit={submitVerification} onTerminate={endCall} />}
    </div>
  );
}
