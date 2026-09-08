import { useState } from "react";
import { Lock, Unlock } from "lucide-react";
import type { ActionFeedback } from "../hooks/useCallSession";

interface WireTransferPanelProps {
  locked: boolean;
  feedback: ActionFeedback | null;
  onAttempt: (amount: number) => void;
}

export default function WireTransferPanel({ locked, feedback, onAttempt }: WireTransferPanelProps) {
  const [amount, setAmount] = useState(50000);

  return (
    <div className="panel p-4">
      <h2 className="text-sm font-medium text-paper">Enterprise workflow</h2>

      <label className="mt-4 block text-xs text-mute" htmlFor="wire-amount">
        Transfer amount (₹)
      </label>
      <input
        id="wire-amount"
        type="number"
        min={0}
        step={1000}
        value={amount}
        onChange={(e) => setAmount(Number(e.target.value))}
        className="tabular mt-1 w-full border border-ink-600 bg-ink-900 px-3 py-2 font-mono text-sm text-paper outline-none focus:border-signal"
      />

      <button
        onClick={() => onAttempt(amount)}
        className={`mt-4 flex w-full items-center justify-center gap-2 border px-4 py-2.5 text-sm font-medium transition-colors ${
          locked
            ? "border-danger/50 bg-danger-bg text-danger hover:bg-danger/15"
            : "border-signal/50 bg-signal-bg text-signal hover:bg-signal/15"
        }`}
      >
        {locked ? <Lock size={15} /> : <Unlock size={15} />}
        Approve wire transfer
      </button>

      {feedback && (
        <p className={`mt-3 text-xs leading-snug ${feedback.ok ? "text-safe" : "text-danger"}`}>
          {feedback.message}
        </p>
      )}
    </div>
  );
}
