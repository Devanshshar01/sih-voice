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
    top: "#2A4D88",   // Deep Blue
    bottom: "#B1BBC8",// Glacial Salt
    peak: "#19315A",   // Navy Peak
    glow: "rgba(42, 77, 136, 0.20)",
  },
  WARN: {
    top: "#D97706",   // Amber 600
    bottom: "#FDE68A",// Amber 200
    peak: "#B45309",   // Dark Amber Peak
    glow: "rgba(217, 119, 6, 0.20)",
  },
  LOCK_VERIFY: {
    top: "#DC2626",   // Red 600
    bottom: "#FECACA",// Red 200
    peak: "#991B1B",   // Dark Red Peak
    glow: "rgba(220, 38, 38, 0.25)",
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

      // Frequency grid background
      ctx.strokeStyle = "rgba(163, 184, 202, 0.08)";
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
    <div className="relative overflow-hidden rounded-2xl border border-forensic-border bg-forensic-panel/70 shadow-panel backdrop-blur">
      {/* Header Bar */}
      <div className="flex items-center justify-between border-b border-forensic-border bg-forensic-surface/60 px-4 py-2.5 text-xs">
        <div className="flex items-center gap-2 text-forensic-muted">
          <Activity size={14} className="text-forensic-accent animate-pulse" />
          <span className="font-bold text-forensic-text tracking-wide">Acoustic Spectrogram &amp; Voice Energy</span>
          <span className="text-forensic-muted/50">·</span>
          <span className="font-mono text-[11px] text-forensic-muted">16.0 kHz Mono PCM</span>
        </div>
        <div className="flex items-center gap-3 font-mono text-[11px]">
          <span className="text-forensic-muted">
            Peak: <span className="text-forensic-text font-semibold">{peakDb}</span>
          </span>
          <span className="inline-flex items-center gap-1.5 rounded-full bg-forensic-accentMuted px-2.5 py-0.5 text-[10px] font-semibold text-forensic-accent">
            <span className="h-1.5 w-1.5 rounded-full bg-forensic-accent animate-pulse" />
            VAD Stream
          </span>
        </div>
      </div>

      {/* Main Canvas Viewport */}
      <div className="relative h-32 sm:h-36 w-full p-2.5">
        <canvas ref={canvasRef} className="h-full w-full rounded-xl" />
      </div>

      {/* Frequency Ticks Footer */}
      <div className="flex justify-between border-t border-forensic-border bg-forensic-surface/40 px-4 py-1.5 font-mono text-[10px] text-forensic-muted">
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

