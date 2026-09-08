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
  const rationale = telemetry?.rationale ?? [];
  const showVerification = status === "LOCK_VERIFY" && !verified;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <main className="min-h-0 flex-1 overflow-y-auto px-4 py-5 sm:px-6 sm:py-6 lg:px-8">
        <div className="mx-auto max-w-[1440px]">
        <StatusBanner status={displayStatus} rationale={rationale} verified={verified} />

        <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border border-ink-600 bg-ink-800/50 px-4 py-3 text-xs">
          <div>
            <p className="font-medium text-paper">Protected call monitor</p>
            <p className="mt-1 text-mute">{meta?.audioMode === "live" ? "Listening to live microphone input" : "Running a controlled scenario for demonstration"}</p>
          </div>
          <div className="flex items-center gap-4 text-mute">
            <span>Window <strong className="font-mono font-medium text-paper">2.0s</strong></span>
            <span>Updates <strong className="font-mono font-medium text-paper">0.5s</strong></span>
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

            {meta?.audioMode === "live" && (
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
              </div>
            )}
          </div>

          <div className="space-y-4">
            <ThreatBreakdown
              acousticScore={acousticScore}
              intentScore={intentScore}
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
