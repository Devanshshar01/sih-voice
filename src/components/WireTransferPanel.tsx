import { useState } from "react";
import { CheckCircle2, Lock, ShieldAlert, Unlock } from "lucide-react";
import type { ActionFeedback } from "../hooks/useCallSession";
import StatusBadge from "./StatusBadge";

interface WireTransferPanelProps {
  locked: boolean;
  pending: boolean;
  feedback: ActionFeedback | null;
  onAttempt: (amount: number) => void;
}

export default function WireTransferPanel({
  locked,
  pending,
  feedback,
  onAttempt,
}: WireTransferPanelProps) {
  const [amount, setAmount] = useState(50000);

  const presets = [10000, 50000, 250000];

  return (
    <section className="rounded-3xl border border-forensic-border bg-forensic-panel/70 p-6 shadow-panel backdrop-blur">
      {/* Header */}
      <div className="flex items-start justify-between gap-3 border-b border-forensic-border pb-3.5">
        <div>
          <p className="eyebrow text-forensic-accent">Protected Enterprise Action</p>
          <h2 className="mt-0.5 text-sm font-bold text-forensic-text">
            Financial Wire Clearance Simulation
          </h2>
        </div>
        <StatusBadge
          label={locked ? "Gated By Policy" : "Clearance Nominal"}
          variant={locked ? "danger" : "safe"}
          pulse={locked}
          size="sm"
        />
      </div>

      <p className="mt-3 text-xs leading-relaxed text-forensic-muted font-sans">
        Simulated high-value transaction. When acoustic or conversational fraud indicators escalate,
        clearance is automatically gated until secondary out-of-band challenge verifies caller identity.
      </p>

      {/* Amount Input */}
      <div className="mt-4">
        <div className="flex items-center justify-between">
          <label className="field-label" htmlFor="wire-amount">
            Wire Authorization Amount (INR)
          </label>
          <span className="font-mono text-[10px] text-forensic-muted">Instant RTGS / NEFT</span>
        </div>
        <div className="relative mt-1.5">
          <span className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3.5 font-mono text-sm text-forensic-muted">
            ₹
          </span>
          <input
            id="wire-amount"
            type="number"
            min={1}
            step={1000}
            value={amount}
            onChange={(e) => setAmount(Math.max(0, Number(e.target.value)))}
            className="field-input pl-8 font-mono text-base font-bold"
            placeholder="50000"
          />
        </div>

        {/* Quick Presets */}
        <div className="mt-2.5 flex gap-2 font-mono">
          {presets.map((preset) => (
            <button
              type="button"
              key={preset}
              onClick={() => setAmount(preset)}
              className={`rounded-xl border px-3 py-1 text-xs transition-colors ${
                amount === preset
                  ? "border-forensic-accent bg-forensic-accentMuted text-forensic-text font-bold"
                  : "border-forensic-border bg-forensic-surface/60 text-forensic-muted hover:border-forensic-accent/40 hover:text-forensic-text"
              }`}
            >
              ₹{preset.toLocaleString("en-IN")}
            </button>
          ))}
        </div>
      </div>

      {/* Action Button */}
      <button
        onClick={() => onAttempt(amount)}
        disabled={pending || !Number.isFinite(amount) || amount <= 0}
        className={`mt-4 flex w-full items-center justify-center gap-2 rounded-2xl border px-4 py-3 text-xs font-extrabold uppercase tracking-wider transition-all ${
          locked
            ? "border-danger/50 bg-danger-bg text-danger hover:bg-danger/20"
            : "border-forensic-accent/50 bg-forensic-accentMuted text-forensic-text hover:bg-forensic-accent/20"
        } disabled:cursor-not-allowed disabled:opacity-50`}
      >
        {pending ? (
          <>
            <span className="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent" />
            <span>Verifying Transaction Clearance...</span>
          </>
        ) : locked ? (
          <>
            <Lock size={15} />
            <span>Attempt Authorization (Gated)</span>
          </>
        ) : (
          <>
            <Unlock size={15} />
            <span>Authorize Wire Transfer</span>
          </>
        )}
      </button>

      {/* Feedback Alert */}
      {feedback && (
        <div
          role="status"
          className={`mt-3.5 flex items-start gap-2.5 rounded-2xl border p-3.5 text-xs leading-relaxed font-sans ${
            feedback.ok
              ? "border-safe/30 bg-safe-bg text-safe"
              : "border-danger/40 bg-danger-bg text-danger"
          }`}
        >
          {feedback.ok ? (
            <CheckCircle2 size={16} className="shrink-0 mt-0.5" />
          ) : (
            <ShieldAlert size={16} className="shrink-0 mt-0.5" />
          )}
          <div>
            <span className="font-bold uppercase tracking-wider block">
              {feedback.ok ? "Clearance Approved" : "Clearance Intercepted"}
            </span>
            <span>{feedback.message}</span>
          </div>
        </div>
      )}
    </section>
  );
}

