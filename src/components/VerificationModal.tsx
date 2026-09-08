import { useEffect, useState } from "react";
import { PhoneOff, Send, ShieldAlert } from "lucide-react";
import type { VerificationState } from "../hooks/useCallSession";

interface VerificationModalProps {
  verification: VerificationState;
  onRequestCode: () => void;
  onInputChange: (value: string) => void;
  onSubmit: () => void;
  onTerminate: () => void;
}

export default function VerificationModal({
  verification,
  onRequestCode,
  onInputChange,
  onSubmit,
  onTerminate,
}: VerificationModalProps) {
  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, []);

  const remaining = verification.requestedAt
    ? Math.max(0, verification.expiresInSeconds - Math.floor((now - verification.requestedAt) / 1000))
    : null;
  const expired = remaining === 0;
  const showCodeEntry = verification.demoCode && !expired;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink-950/80 p-4 backdrop-blur-sm">
      <div className="w-full max-w-sm border border-danger/40 bg-ink-800">
        <div className="flex items-center gap-2 border-b border-danger/30 bg-danger-bg px-5 py-4 text-danger">
          <ShieldAlert size={18} />
          <h2 className="text-sm font-medium">Security override required</h2>
        </div>

        <div className="px-5 py-5">
          <p className="text-sm text-paper-dim">
            Complete out-of-band verification to unlock this call's sensitive controls.
          </p>

          {!showCodeEntry ? (
            <>
              {expired && <p className="mt-3 text-xs text-warn">Previous code expired. Request a new one.</p>}
              <button
                onClick={onRequestCode}
                disabled={verification.requesting}
                className="mt-4 flex w-full items-center justify-center gap-2 border border-signal/50 bg-signal-bg px-4 py-2.5 text-sm font-medium text-signal transition-colors hover:bg-signal/15 disabled:opacity-60"
              >
                <Send size={15} />
                {verification.requesting ? "Sending…" : "Send push prompt to registered device"}
              </button>
            </>
          ) : (
            <>
              <div className="mt-4 border border-ink-600 bg-ink-900 px-3 py-2">
                <p className="text-xs text-mute">Demo delivery — sent to registered device</p>
                <p className="tabular mt-1 font-mono text-lg tracking-[0.3em] text-paper">
                  {verification.demoCode}
                </p>
              </div>

              <label className="mt-4 block text-xs text-mute" htmlFor="totp-input">
                Enter 6-digit code
              </label>
              <input
                id="totp-input"
                inputMode="numeric"
                maxLength={6}
                value={verification.input}
                onChange={(e) => onInputChange(e.target.value.replace(/\D/g, "").slice(0, 6))}
                className="tabular mt-1 w-full border border-ink-600 bg-ink-900 px-3 py-2 text-center font-mono text-lg tracking-[0.4em] text-paper outline-none focus:border-signal"
                placeholder="------"
              />

              <div className="mt-2 flex items-center justify-between text-xs">
                <span className="text-mute">Code expires in</span>
                <span className="tabular font-mono text-paper">{remaining}s</span>
              </div>

              {verification.error && <p className="mt-2 text-xs text-danger">{verification.error}</p>}

              <button
                onClick={onSubmit}
                disabled={verification.input.length !== 6 || verification.submitting}
                className="mt-4 w-full border border-signal/50 bg-signal-bg px-4 py-2.5 text-sm font-medium text-signal transition-colors hover:bg-signal/15 disabled:opacity-40"
              >
                {verification.submitting ? "Verifying…" : "Verify and unlock"}
              </button>
            </>
          )}

          <button
            onClick={onTerminate}
            className="mt-3 flex w-full items-center justify-center gap-2 border border-ink-600 px-4 py-2.5 text-sm text-mute transition-colors hover:border-danger/50 hover:text-danger"
          >
            <PhoneOff size={15} />
            Terminate suspect call
          </button>
        </div>
      </div>
    </div>
  );
}
