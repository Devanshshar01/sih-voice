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
  const score = telemetry?.risk_score ?? 0;
  const acousticScore = telemetry?.acoustic_score ?? 0;
  const intentScore = telemetry?.intent_score ?? 0;
  const rationale = telemetry?.rationale ?? [];
  const showVerification = status === "LOCK_VERIFY" && !verified;

  return (
    <div className="flex min-h-screen flex-col">
      <div className="flex-1 px-4 py-4 sm:px-6 sm:py-6">
        <StatusBanner status={status} rationale={rationale} />

        <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-[1.2fr_0.8fr]">
          <div className="space-y-4">
            <div className="panel flex flex-col items-center justify-center p-6">
              {telemetry ? (
                <TrustGauge score={score} status={status} />
              ) : (
                <p className="py-10 text-sm text-mute">Calibrating baseline signal…</p>
              )}
            </div>

            <div>
              <p className="mb-2 text-xs text-mute">Live signal</p>
              <Spectrograph analyser={analyser} status={status} />
            </div>

            {meta?.audioMode === "live" && (
              <div className="panel p-4">
                <label className="block text-xs text-mute" htmlFor="live-transcript">
                  Conversation notes — feeds the intent analyzer (live transcription isn't wired in yet)
                </label>
                <textarea
                  id="live-transcript"
                  value={liveTranscript}
                  onChange={(e) => updateLiveTranscript(e.target.value)}
                  rows={2}
                  placeholder="Type what the caller is asking for, as it happens…"
                  className="mt-1 w-full resize-none border border-ink-600 bg-ink-900 px-3 py-2 text-sm text-paper outline-none focus:border-signal"
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
              onAttempt={attemptWireTransfer}
            />
          </div>
        </div>
      </div>

      <CallControls muted={muted} onHold={onHold} onToggleMute={toggleMute} onToggleHold={toggleHold} onEndCall={endCall} />

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
