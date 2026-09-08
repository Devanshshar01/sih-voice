import { useCallSession } from "./hooks/useCallSession";
import NavHeader from "./components/NavHeader";
import StartCallForm from "./components/StartCallForm";
import CallDashboard from "./components/CallDashboard";
import ForensicsView from "./components/ForensicsView";

export default function App() {
  const session = useCallSession();
  const { phase, meta, error, wsConnected, durationSeconds, startNewCall } = session;

  if (phase === "idle" || phase === "connecting") {
    return <StartCallForm onStart={startNewCall} error={error} connecting={phase === "connecting"} />;
  }

  return (
    <div className="min-h-screen bg-ink-900">
      <NavHeader
        connected={wsConnected}
        ended={phase === "ended"}
        callerId={meta?.callerId}
        recipientId={meta?.recipientId}
        durationSeconds={phase === "active" ? durationSeconds : undefined}
      />
      {phase === "active" && <CallDashboard session={session} />}
      {phase === "ended" && <ForensicsView session={session} />}
    </div>
  );
}
