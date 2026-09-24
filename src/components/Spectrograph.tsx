import { useEffect, useRef, useState } from "react";
import { Activity } from "lucide-react";
import type { RiskStatus } from "../types";

interface SpectrographProps {
  analyser: AnalyserNode | null;
  status: RiskStatus;
}

const BAR_COUNT = 56;

const STATUS_PALETTES: Record<RiskStatus, { top: string; bottom: string; peak: string; glow: string }> = {
  ALLOW: {
    top: "#00f0ff",
    bottom: "#0284c7",
    peak: "#38bdf8",
    glow: "rgba(0, 240, 255, 0.2)",
  },
  WARN: {
    top: "#f59e0b",
    bottom: "#b45309",
    peak: "#fde047",
    glow: "rgba(245, 158, 11, 0.25)",
  },
  LOCK_VERIFY: {
    top: "#ef4444",
    bottom: "#991b1b",
    peak: "#fca5a5",
    glow: "rgba(239, 68, 68, 0.3)",
  },
};

export default function Spectrograph({ analyser, status }: SpectrographProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const rafRef = useRef<number | undefined>(undefined);
  const phaseRef = useRef(0);
  const peaksRef = useRef<number[]>(new Array(BAR_COUNT).fill(0));
  const [peakDb, setPeakDb] = useState("-inf");

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
    const palette = STATUS_PALETTES[status];
    const noiseAmount = status === "LOCK_VERIFY" ? 0.6 : status === "WARN" ? 0.35 : 0.08;

    let frameCounter = 0;

    const draw = () => {
      const bounds = canvas.getBoundingClientRect();
      const { width, height } = bounds;
      ctx.clearRect(0, 0, width, height);

      // Subtle frequency grid background
      ctx.strokeStyle = "rgba(255, 255, 255, 0.03)";
      ctx.lineWidth = 1;
      const gridSteps = 4;
      for (let g = 1; g < gridSteps; g++) {
        const y = (height / gridSteps) * g;
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(width, y);
        ctx.stroke();
      }

      const barWidth = width / BAR_COUNT;
      const values: number[] = [];
      let currentMax = 0;

      if (analyser && freqData) {
        analyser.getByteFrequencyData(freqData);
        const step = Math.max(1, Math.floor(freqData.length / BAR_COUNT));
        for (let i = 0; i < BAR_COUNT; i++) {
          const val = freqData[i * step] / 255;
          values.push(val);
          if (val > currentMax) currentMax = val;
        }
      } else {
        // Idle trace when live stream is calibrating
        phaseRef.current += 0.08;
        for (let i = 0; i < BAR_COUNT; i++) {
          const base = 0.16 + 0.14 * Math.sin(phaseRef.current + i * 0.28);
          const jitter = (Math.sin(phaseRef.current * 2.3 + i * 1.1) * 0.5 + 0.5) * noiseAmount;
          const val = Math.max(0.02, Math.min(1, base + jitter));
          values.push(val);
          if (val > currentMax) currentMax = val;
        }
      }

      // Update peaks
      for (let i = 0; i < BAR_COUNT; i++) {
        const current = values[i];
        if (current >= peaksRef.current[i]) {
          peaksRef.current[i] = current;
        } else {
          peaksRef.current[i] = Math.max(0, peaksRef.current[i] - 0.015);
        }
      }

      // Render vertical frequency bars
      values.forEach((v, i) => {
        const barHeight = Math.max(3, v * (height - 8));
        const x = i * barWidth;
        const xPadding = barWidth * 0.18;
        const actualWidth = barWidth * 0.64;
        const y = height - barHeight;

        const gradient = ctx.createLinearGradient(0, y, 0, height);
        gradient.addColorStop(0, palette.top);
        gradient.addColorStop(1, palette.bottom);

        ctx.fillStyle = gradient;
        ctx.fillRect(x + xPadding, y, actualWidth, barHeight);

        // Peak line
        const peakY = height - Math.max(3, peaksRef.current[i] * (height - 8));
        ctx.fillStyle = palette.peak;
        ctx.fillRect(x + xPadding, peakY, actualWidth, 1.5);
      });

      // Update max dB readout periodically (every 10 frames)
      frameCounter++;
      if (frameCounter % 10 === 0) {
        if (currentMax > 0.01) {
          const db = Math.round(20 * Math.log10(currentMax));
          setPeakDb(`${db} dBFS`);
        } else {
          setPeakDb("-inf");
        }
      }

      rafRef.current = requestAnimationFrame(draw);
    };

    draw();
    return () => {
      if (rafRef.current !== undefined) cancelAnimationFrame(rafRef.current);
    };
  }, [analyser, status]);

  return (
    <div className="relative overflow-hidden rounded-2xl border border-ink-700/40 bg-ink-900/80 shadow-panel">
      {/* Header Bar */}
      <div className="flex items-center justify-between border-b border-ink-700/40 bg-ink-850/60 px-4 py-2 text-xs">
        <div className="flex items-center gap-2 text-paper-dim">
          <Activity size={14} className="text-signal animate-pulse" />
          <span className="font-semibold tracking-wide">Spectral Energy &amp; Voice Activity</span>
          <span className="text-ink-600">·</span>
          <span className="font-mono text-[11px] text-paper-muted">16.0 kHz Mono</span>
        </div>
        <div className="flex items-center gap-3 font-mono text-[11px]">
          <span className="text-paper-muted">
            Peak: <span className="text-paper-bright font-semibold">{peakDb}</span>
          </span>
          <span className="inline-flex items-center gap-1 rounded-full bg-signal-bg px-2 py-0.5 text-[10px] font-medium text-signal">
            <span className="h-1.5 w-1.5 rounded-full bg-signal animate-pulse" />
            VAD Stream
          </span>
        </div>
      </div>

      {/* Main Canvas Viewport */}
      <div className="relative h-32 sm:h-36 w-full p-2">
        <canvas ref={canvasRef} className="h-full w-full rounded-lg" />
      </div>

      {/* Frequency Ticks Footer */}
      <div className="flex justify-between border-t border-ink-700/30 bg-ink-850/40 px-4 py-1.5 font-mono text-[10px] text-paper-muted">
        <span>100 Hz</span>
        <span>500 Hz</span>
        <span>1.0 kHz</span>
        <span>2.5 kHz</span>
        <span>5.0 kHz</span>
        <span>8.0 kHz</span>
      </div>
    </div>
  );
}
