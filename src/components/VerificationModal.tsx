import { useEffect, useState } from "react";
import { Copy, KeyRound, PhoneOff, Send, ShieldAlert, Timer } from "lucide-react";
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
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, []);

  const remaining = verification.requestedAt
    ? Math.min(
        verification.expiresInSeconds,
        Math.max(0, verification.expiresInSeconds - Math.floor((now - verification.requestedAt) / 1000))
      )
    : null;
  const expired = remaining === 0;
  const showCodeEntry = verification.deliveredCode && !expired;

  const copyCode = async () => {
    if (!verification.deliveredCode) return;
    try {
      await navigator.clipboard.writeText(verification.deliveredCode);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopied(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-forensic-bg/85 p-4 backdrop-blur-xl animate-fadeIn">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="verification-modal-title"
        aria-describedby="verification-modal-desc"
        className="w-full max-w-md overflow-hidden rounded-3xl border border-danger/50 bg-forensic-panel shadow-elevated"
      >
        {/* Modal Header */}
        <div className="flex items-center gap-3 border-b border-danger/40 bg-danger-bg p-5 text-danger">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl border border-danger/50 bg-danger/20 text-danger animate-pulse">
            <ShieldAlert size={19} />
          </div>
          <div>
            <h2 id="verification-modal-title" className="text-sm font-extrabold tracking-wide uppercase font-sans">
              Out-of-Band Security Override
            </h2>
            <span className="font-mono text-[10px] text-danger font-bold">POLICY LOCKDOWN ENFORCED</span>
          </div>
        </div>

        {/* Modal Body */}
        <div className="p-6 space-y-5">
          <p id="verification-modal-desc" className="text-xs leading-relaxed text-forensic-muted font-sans">
            The voice stream triggered high-confidence impersonation or deepfake markers. Sensitive
            financial actions are held until the caller passes out-of-band biometric/SMS challenge.
          </p>

          {!showCodeEntry ? (
            <div className="space-y-3 font-sans">
              {expired && (
                <p className="rounded-xl border border-warn/40 bg-warn-bg p-3 text-center text-xs text-warn">
                  Previous verification challenge expired. Request a new code.
                </p>
              )}
              <button
                onClick={onRequestCode}
                disabled={verification.requesting}
                className="flex w-full items-center justify-center gap-2 rounded-2xl border border-forensic-accent/50 bg-forensic-accentMuted px-4 py-3 text-xs font-bold uppercase tracking-wider text-forensic-accent transition-all hover:bg-forensic-accent/30 disabled:opacity-50"
              >
                <Send size={14} />
                <span>
                  {verification.requesting
                    ? "Dispatching Push Challenge..."
                    : "Dispatch Challenge to Enrolled Device"}
                </span>
              </button>
            </div>
          ) : (
            <div className="space-y-4">
              {/* Delivered Code Display (for testing environment) */}
              <div className="rounded-2xl border border-forensic-border bg-forensic-surface p-3.5">
                <div className="flex items-center justify-between">
                  <span className="text-[10px] font-mono uppercase text-forensic-muted font-bold">
                    In-Band Sandbox Challenge Code
                  </span>
                  <button
                    type="button"
                    onClick={copyCode}
                    className="flex items-center gap-1 font-mono text-[10px] text-forensic-muted hover:text-forensic-accent transition-colors"
                  >
                    <Copy size={11} />
                    <span>{copied ? "Copied" : "Copy"}</span>
                  </button>
                </div>
                <div className="mt-2 flex items-center justify-between">
                  <span className="tabular font-mono text-2xl font-black tracking-[0.35em] text-forensic-accent">
                    {verification.deliveredCode}
                  </span>
                  <span className="font-mono text-[10px] text-forensic-muted">AUTO-GENERATED</span>
                </div>
              </div>

              {/* Code Entry Input */}
              <div>
                <label className="field-label" htmlFor="totp-input">
                  Enter 6-Digit Verification Token
                </label>
                <input
                  id="totp-input"
                  autoFocus
                  inputMode="numeric"
                  maxLength={6}
                  value={verification.input}
                  onChange={(e) => onInputChange(e.target.value.replace(/\D/g, "").slice(0, 6))}
                  className="field-input mt-1.5 text-center font-mono text-xl tracking-[0.5em] font-bold text-forensic-text"
                  placeholder="------"
                />
              </div>

              {/* Expiry Countdown */}
              <div className="flex items-center justify-between font-mono text-xs text-forensic-muted">
                <span className="flex items-center gap-1">
                  <Timer size={12} className="text-warn" />
                  <span>Challenge validity:</span>
                </span>
                <span className="tabular font-bold text-forensic-text">{remaining}s remaining</span>
              </div>

              {/* Verification Error */}
              {verification.error && (
                <p className="rounded-2xl border border-danger/40 bg-danger-bg p-3 text-xs text-danger font-sans">
                  {verification.error}
                </p>
              )}

              {/* Submit Button */}
              <button
                onClick={onSubmit}
                disabled={verification.input.length !== 6 || verification.submitting}
                className="flex w-full items-center justify-center gap-2 rounded-2xl border border-safe/40 bg-safe-bg px-4 py-2.5 text-xs font-bold uppercase tracking-wider text-safe transition-all hover:bg-safe/20 disabled:cursor-not-allowed disabled:opacity-50"
              >
                <KeyRound size={14} />
                <span>{verification.submitting ? "Validating Token..." : "Verify & Unlock Session"}</span>
              </button>
            </div>
          )}

          {/* Emergency Sever Call Button */}
          <div className="border-t border-forensic-border pt-4">
            <button
              onClick={onTerminate}
              className="flex w-full items-center justify-center gap-2 rounded-2xl border border-forensic-border bg-forensic-surface px-4 py-2.5 text-xs font-sans text-forensic-muted transition-colors hover:border-danger/60 hover:bg-danger-bg hover:text-danger"
            >
              <PhoneOff size={14} />
              <span>Sever &amp; Terminate Suspect Call</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

