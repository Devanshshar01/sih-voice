import { useMemo } from "react";
import { Download, RotateCcw } from "lucide-react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceArea,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { UseCallSession } from "../hooks/useCallSession";

interface ForensicsViewProps {
  session: UseCallSession;
}

export default function ForensicsView({ session }: ForensicsViewProps) {
  const { meta, telemetryHistory, serverRiskSnapshot, durationSeconds, startOver } = session;

  const chartData = useMemo(() => {
    if (telemetryHistory.length === 0) return [];
    const t0 = telemetryHistory[0].timestamp;
    return telemetryHistory.map((point) => ({
      t: Number((point.timestamp - t0).toFixed(1)),
      score: point.risk_score,
    }));
  }, [telemetryHistory]);

  const maxScore = telemetryHistory.reduce((max, p) => Math.max(max, p.risk_score), 0);
  const flaggedEvents = telemetryHistory.filter((p) => p.status !== "ALLOW");

  const handleExport = () => {
    const report = {
      call_id: meta?.callId,
      caller_id: meta?.callerId,
      recipient_id: meta?.recipientId,
      duration_seconds: durationSeconds,
      max_risk_score: maxScore,
      telemetry: telemetryHistory,
      server_risk_snapshot: serverRiskSnapshot,
      exported_at: new Date().toISOString(),
    };
    const blob = new Blob([JSON.stringify(report, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `voicetrust-incident-${meta?.callId ?? "unknown"}.json`;
    link.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="mx-auto max-w-4xl px-4 py-6 sm:px-6">
      <div className="flex items-start justify-between">
        <div>
          <p className="text-xs text-mute">Post-call forensic overview</p>
          <h1 className="mt-1 text-xl font-medium text-paper">{meta?.callerId ?? "Unknown caller"}</h1>
          <p className="mt-1 font-mono text-xs text-mute">{meta?.callId}</p>
        </div>
        <button
          onClick={startOver}
          className="flex items-center gap-2 border border-ink-600 px-3 py-2 text-xs text-paper-dim transition-colors hover:border-signal/50 hover:text-signal"
        >
          <RotateCcw size={14} />
          New call
        </button>
      </div>

      <div className="mt-6 grid grid-cols-3 gap-3">
        <div className="panel p-3">
          <p className="text-xs text-mute">Duration</p>
          <p className="tabular mt-1 font-mono text-lg text-paper">
            {Math.floor(durationSeconds / 60)}:{(durationSeconds % 60).toString().padStart(2, "0")}
          </p>
        </div>
        <div className="panel p-3">
          <p className="text-xs text-mute">Peak trust index</p>
          <p
            className={`tabular mt-1 font-mono text-lg ${
              maxScore >= 70 ? "text-danger" : maxScore >= 40 ? "text-warn" : "text-safe"
            }`}
          >
            {maxScore}/100
          </p>
        </div>
        <div className="panel p-3">
          <p className="text-xs text-mute">Flagged windows</p>
          <p className="tabular mt-1 font-mono text-lg text-paper">{flaggedEvents.length}</p>
        </div>
      </div>

      <div className="panel mt-4 p-4">
        <p className="text-sm font-medium text-paper">Risk score timeline</p>
        <div className="mt-3 h-56">
          {chartData.length > 0 ? (
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={chartData} margin={{ top: 4, right: 8, left: -20, bottom: 0 }}>
                <CartesianGrid stroke="#1b262e" vertical={false} />
                <ReferenceArea y1={0} y2={40} fill="#1a4a3a" fillOpacity={0.35} />
                <ReferenceArea y1={40} y2={70} fill="#4a3a17" fillOpacity={0.35} />
                <ReferenceArea y1={70} y2={100} fill="#4a2320" fillOpacity={0.35} />
                <XAxis dataKey="t" tickFormatter={(v) => `${v}s`} stroke="#546069" fontSize={11} />
                <YAxis domain={[0, 100]} stroke="#546069" fontSize={11} />
                <Tooltip
                  contentStyle={{ background: "#0f171d", border: "1px solid #25333c", fontSize: 12 }}
                  labelFormatter={(v) => `t = ${v}s`}
                  formatter={(value: number) => [`${value}/100`, "Trust index"]}
                />
                <Line type="monotone" dataKey="score" stroke="#4fc3f7" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          ) : (
            <p className="flex h-full items-center justify-center text-sm text-mute">
              No telemetry captured for this call.
            </p>
          )}
        </div>
      </div>

      <div className="panel mt-4 p-4">
        <p className="text-sm font-medium text-paper">Flagged events</p>
        {flaggedEvents.length === 0 ? (
          <p className="mt-2 text-sm text-mute">No anomalies were flagged during this call.</p>
        ) : (
          <ul className="mt-3 divide-y divide-ink-600">
            {flaggedEvents.map((event, i) => (
              <li key={i} className="py-2.5">
                <div className="flex items-center justify-between">
                  <span
                    className={`text-xs font-medium ${
                      event.status === "LOCK_VERIFY" ? "text-danger" : "text-warn"
                    }`}
                  >
                    {event.status === "LOCK_VERIFY" ? "Locked" : "Warning"} — {event.risk_score}/100
                  </span>
                  <span className="tabular font-mono text-xs text-mute">
                    {new Date(event.timestamp * 1000).toLocaleTimeString()}
                  </span>
                </div>
                <p className="mt-1 text-sm text-paper-dim">{event.rationale[0]}</p>
              </li>
            ))}
          </ul>
        )}
      </div>

      <button
        onClick={handleExport}
        className="mt-4 flex items-center gap-2 border border-ink-600 px-4 py-2.5 text-sm text-paper-dim transition-colors hover:border-signal/50 hover:text-signal"
      >
        <Download size={15} />
        Export forensic report (JSON)
      </button>
    </div>
  );
}
