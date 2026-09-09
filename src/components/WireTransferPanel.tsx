import { useState } from "react";
import { CheckCircle2, Lock, Unlock } from "lucide-react";
import type { ActionFeedback } from "../hooks/useCallSession";

interface WireTransferPanelProps {
  locked: boolean;
  pending: boolean;
  feedback: ActionFeedback | null;
  onAttempt: (amount: number) => void;
}

export default function WireTransferPanel({ locked, pending, feedback, onAttempt }: WireTransferPanelProps) {
  const [amount, setAmount] = useState(50000);

  return (
    <div className="panel p-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-[11px] uppercase tracking-[0.14em] text-mute">Protected action</p>
          <h2 className="mt-1 text-sm font-medium text-paper">Approve wire transfer</h2>
        </div>
        <span className={`flex items-center gap-1 text-[11px] ${locked ? "text-danger" : "text-safe"}`}>
          {locked ? <Lock size={13} /> : <CheckCircle2 size={13} />}
          {locked ? "Held for review" : "Controls open"}
        </span>
      </div>

      <label className="mt-4 block text-xs text-mute" htmlFor="wire-amount">
        Transfer amount (INR)
      </label>
      <input
        id="wire-amount"
        type="number"
        min={0}
        step={1000}
        value={amount}
        onChange={(e) => setAmount(Number(e.target.value))}
        className="field-input tabular"
      />

      <button
        onClick={() => onAttempt(amount)}
        disabled={pending || !Number.isFinite(amount) || amount <= 0}
        className={`mt-4 flex w-full items-center justify-center gap-2 border px-4 py-2.5 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-signal disabled:cursor-not-allowed disabled:opacity-50 ${
          locked
            ? "border-danger/50 bg-danger-bg text-danger hover:bg-danger/15"
            : "border-signal/50 bg-signal-bg text-signal hover:bg-signal/15"
        }`}
      >
        {locked ? <Lock size={15} /> : <Unlock size={15} />}
        {pending ? "Authorizing..." : locked ? "Request verification to approve" : "Approve wire transfer"}
      </button>

      {feedback && (
        <p role="status" className={`mt-3 border px-3 py-2 text-xs leading-snug ${feedback.ok ? "border-safe/30 bg-safe-bg text-safe" : "border-danger/30 bg-danger-bg text-danger"}`}>
          {feedback.message}
        </p>
      )}
    </div>
  );
}
