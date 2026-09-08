import { useEffect, useRef } from "react";
import type { RiskStatus } from "../types";

interface SpectrographProps {
  analyser: AnalyserNode | null;
  status: RiskStatus;
}

const STATUS_COLOR: Record<RiskStatus, string> = {
  ALLOW: "#4fc3f7",
  WARN: "#f5a524",
  LOCK_VERIFY: "#f0554a",
};

const BAR_COUNT = 48;

export default function Spectrograph({ analyser, status }: SpectrographProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const rafRef = useRef<number | undefined>(undefined);
  const phaseRef = useRef(0);

  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return;

    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    ctx.scale(dpr, dpr);

    const freqData = analyser ? new Uint8Array(analyser.frequencyBinCount) : null;
    const noiseAmount = status === "LOCK_VERIFY" ? 0.55 : status === "WARN" ? 0.3 : 0.08;
    const color = STATUS_COLOR[status];

    const draw = () => {
      const bounds = canvas.getBoundingClientRect();
      const { width, height } = bounds;
      ctx.clearRect(0, 0, width, height);

      const barWidth = width / BAR_COUNT;
      const values: number[] = [];

      if (analyser && freqData) {
        analyser.getByteFrequencyData(freqData);
        const step = Math.max(1, Math.floor(freqData.length / BAR_COUNT));
        for (let i = 0; i < BAR_COUNT; i++) {
          values.push(freqData[i * step] / 255);
        }
      } else {
        // Demo mode: a deterministic, non-random-looking trace whose
        // roughness scales with the current risk status.
        phaseRef.current += 0.09;
        for (let i = 0; i < BAR_COUNT; i++) {
          const base = 0.22 + 0.18 * Math.sin(phaseRef.current + i * 0.35);
          const jitter = (Math.sin(phaseRef.current * 2.7 + i * 1.3) * 0.5 + 0.5) * noiseAmount;
          values.push(Math.max(0.02, Math.min(1, base + jitter)));
        }
      }

      values.forEach((v, i) => {
        const barHeight = Math.max(2, v * height);
        const x = i * barWidth;
        ctx.fillStyle = color;
        ctx.globalAlpha = 0.9;
        ctx.fillRect(x + barWidth * 0.18, height - barHeight, barWidth * 0.64, barHeight);
      });

      rafRef.current = requestAnimationFrame(draw);
    };

    draw();
    return () => {
      if (rafRef.current !== undefined) cancelAnimationFrame(rafRef.current);
    };
  }, [analyser, status]);

  return (
    <div className="relative h-28 w-full overflow-hidden border border-ink-600 bg-ink-950">
      <canvas ref={canvasRef} className="h-full w-full" />
      <div className="pointer-events-none absolute inset-x-0 top-1/2 h-px bg-ink-600" />
    </div>
  );
}
