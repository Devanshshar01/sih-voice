import type { UseCallSession } from "../hooks/useCallSession";
import TrustGauge from "./TrustGauge";
import Spectrograph from "./Spectrograph";
import StatusBanner from "./StatusBanner";
import ThreatBreakdown from "./ThreatBreakdown";
import WireTransferPanel from "./WireTransferPanel";
import CallControls from "./CallControls";
import VerificationModal from "./VerificationModal";

interface CallDashboardProps {
  session: UseCallSession;
}

export default function CallDashboard({ session }: CallDashboardProps) {
  const {
    meta,
    telemetry,
    muted,
    onHold,
    analyser,
    verified,
    verification,
    actionFeedback,
    actionPending,
    liveTranscript,
    browserOnnxStatus,
    browserOnnxResult,
    localRisk,
    localModelError,
    endCall,
    toggleMute,
    toggleHold,
    updateLiveTranscript,
    requestChallenge,
    setVerificationInput,
    submitVerification,
    attemptWireTransfer,
  } = session;

  const status = telemetry?.status ?? "ALLOW";
  const displayStatus = verified ? "ALLOW" : status;
  const score = telemetry?.risk_score ?? 0;
  const acousticScore = telemetry?.acoustic_score ?? 0;
  const intentScore = telemetry?.intent_score ?? 0;
  const identityMismatch = telemetry?.identity_mismatch ?? null;
  const speakerSimilarity = telemetry?.speaker_score ?? null;
  const rationale = telemetry?.rationale ?? [];
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

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <main className="min-h-0 flex-1 overflow-y-auto px-4 py-5 sm:px-6 sm:py-6 lg:px-8">
        <div className="mx-auto max-w-[1440px]">
        <StatusBanner status={displayStatus} rationale={rationale} verified={verified} />

        <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border border-ink-600 bg-ink-800/50 px-4 py-3 text-xs">
          <div>
            <p className="font-medium text-paper">Protected call monitor</p>
            <p className="mt-1 text-mute">{meta && !meta.audioMode.startsWith("demo") ? "Listening to live microphone input" : "Running a controlled scenario for demonstration"}</p>
          </div>
          <div className="flex items-center gap-4 text-mute">
            <span>Window <strong className="font-mono font-medium text-paper">4.0s</strong></span>
            <span>Updates <strong className="font-mono font-medium text-paper">0.5s</strong></span>
            {telemetry?.latency_ms?.total != null && (
              <span>
                Decision <strong className="font-mono font-medium text-paper">{Math.round(telemetry.latency_ms.total)}ms</strong>
                {telemetry.latency_stats?.total && telemetry.latency_stats.total.n >= 4 && (
                  <span className="text-mute/70"> (p95 {Math.round(telemetry.latency_stats.total.p95)}ms)</span>
                )}
              </span>
            )}
            {telemetry?.degraded && Object.keys(telemetry.degraded).length > 0 && (
              <span className="text-warn">Degraded: {Object.keys(telemetry.degraded).join(", ")}</span>
            )}
            <span className={verified ? "text-safe" : "text-signal"}>{verified ? "Override verified" : "Monitoring"}</span>
          </div>
        </div>

        <div className="mt-5 grid grid-cols-1 gap-5 xl:grid-cols-[minmax(0,1.15fr)_minmax(360px,0.85fr)]">
          <div className="space-y-4">
            <div className="surface flex flex-col items-center justify-center px-5 py-6 sm:px-8 sm:py-8">
              {telemetry ? (
                <TrustGauge score={score} status={status} />
              ) : (
                <p className="py-10 text-sm text-mute">Calibrating baseline signal…</p>
              )}
            </div>

            <div className="surface px-5 py-5 sm:px-6">
              <div className="mb-3 flex items-center justify-between gap-3">
                <div>
                  <p className="section-label">Signal activity</p>
                  <p className="mt-1 text-sm text-paper-dim">Frequency trace from the monitored stream</p>
                </div>
                <span className="font-mono text-[11px] text-mute">16 kHz · mono</span>
              </div>
              <Spectrograph analyser={analyser} status={status} />
            </div>

            {(meta?.audioMode === "hybrid" || meta?.audioMode === "edge-local") && (
              <div className="surface p-5 sm:p-6">
                <p className="section-label">Local anti-spoof (in-browser)</p>
                <p className="mt-1 text-sm text-paper-dim">
                  {meta.audioMode === "edge-local"
                    ? "Raw audio never leaves this device. Only derived scores are produced locally — ASR, speaker matching, and policy fusion are unavailable and shown as degraded."
                    : "Anti-spoof runs in this browser; the backend still performs ASR, speaker matching, and policy fusion."}
                </p>
                <div className="mt-4 border border-ink-600 bg-ink-900/60 p-3">
                  <p className="text-xs uppercase tracking-[0.12em] text-mute">Local inference status</p>
                  <p className="mt-2 text-sm text-paper">
                    {browserOnnxStatus === "loading" && "Loading the ONNX model in the browser…"}
                    {browserOnnxStatus === "ready" && browserOnnxResult && (
                      <>
                        Synthetic likelihood: <span className="font-semibold text-signal">{browserOnnxPercent}%</span> · label: {browserOnnxResult.label}
                        {localRisk && (
                          <span className="mt-1 block font-mono text-[11px] text-mute">
                            model {localRisk.modelId} · load {localRisk.modelLoadMs ? Math.round(localRisk.modelLoadMs) : "—"}ms · infer {Math.round(localRisk.inferenceMs)}ms (p50 {localRisk.p50Ms ? Math.round(localRisk.p50Ms) : "—"} / p95 {localRisk.p95Ms ? Math.round(localRisk.p95Ms) : "—"}) · n={localRisk.inferenceCount}
                            {localRisk.heapUsedMb != null && ` · heap ${localRisk.heapUsedMb}MB`}
                          </span>
                        )}
                      </>
                    )}
                    {browserOnnxStatus === "error" && (
                      <span className="text-warn">Local model failed: {localModelError ?? "unknown error"}. Hybrid mode continues on the backend stream; edge mode is degraded.</span>
                    )}
                    {browserOnnxStatus === "idle" && "Waiting for the first audio frame…"}
                  </p>
                </div>
                {meta.audioMode === "edge-local" && (
                  <div className="mt-3 border border-warn/40 bg-warn-bg px-3 py-2 text-xs text-warn">
                    Degraded (offline): conversation transcript, speaker identity, and policy fusion require the cloud pipeline and are intentionally unavailable — raw audio is never uploaded in this mode.
                  </div>
                )}
              </div>
            )}

            {meta?.audioMode === "cloud" && (
              <div className="surface p-5 sm:p-6">
                <label className="section-label" htmlFor="live-transcript">
                  Conversation context
                </label>
                <p className="mt-1 text-sm text-paper-dim">Add a short note when the caller makes a sensitive request.</p>
                <textarea
                  id="live-transcript"
                  value={liveTranscript}
                  onChange={(e) => updateLiveTranscript(e.target.value)}
                  rows={2}
                  placeholder="Type what the caller is asking for, as it happens…"
                  className="field-input mt-3 w-full resize-none font-sans"
                />
                {languageLabel && (
                  <p className="mt-2 text-xs text-mute">
                    Language: <span className="font-medium text-paper">{languageLabel}</span>
                  </p>
                )}
                {intentRisks.length > 0 && (
                  <div className="mt-3 space-y-2">
                    {intentRisks.map((risk, i) => (
                      <div
                        key={`${risk.category}-${risk.matched_phrase}-${i}`}
                        className="border border-ink-600 bg-ink-900/60 px-3 py-2"
                      >
                        <div className="flex items-center justify-between gap-2">
                          <span
                            className={
                              risk.severity === "critical"
                                ? "text-xs font-semibold uppercase tracking-wide text-danger"
                                : risk.severity === "elevated"
                                  ? "text-xs font-semibold uppercase tracking-wide text-warn"
                                  : "text-xs font-semibold uppercase tracking-wide text-mute"
                            }
                          >
                            {risk.category} · {risk.speech_act}
                          </span>
                          <span className="font-mono text-[11px] text-mute">{risk.language}</span>
                        </div>
                        <p className="mt-1 text-sm text-paper-dim">
                          “{risk.matched_phrase}” — {risk.evidence}
                        </p>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>

          <div className="space-y-4">
            <ThreatBreakdown
              acousticScore={acousticScore}
              intentScore={intentScore}
              identityMismatch={identityMismatch}
              speakerSimilarity={speakerSimilarity}
              rationale={rationale}
              status={status}
            />
            <WireTransferPanel
              locked={status === "LOCK_VERIFY" && !verified}
              feedback={actionFeedback}
              pending={actionPending}
              onAttempt={attemptWireTransfer}
            />
          </div>
        </div>
        </div>
      </main>

      <div className="shrink-0 border-t border-ink-700 bg-ink-900/95 px-4 py-3 backdrop-blur-sm sm:px-6">
        <div className="mx-auto max-w-[1440px]">
          <CallControls muted={muted} onHold={onHold} onToggleMute={toggleMute} onToggleHold={toggleHold} onEndCall={endCall} />
        </div>
      </div>

      {showVerification && (
        <VerificationModal
          verification={verification}
          onRequestCode={requestChallenge}
          onInputChange={setVerificationInput}
          onSubmit={submitVerification}
          onTerminate={endCall}
        />
      )}
    </div>
  );
}
