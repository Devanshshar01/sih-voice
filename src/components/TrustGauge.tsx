import { useMemo } from "react";
import type { RiskStatus } from "../types";

interface TrustGaugeProps {
  score: number;
  status: RiskStatus;
}

const START_ANGLE = -135;
const END_ANGLE = 135;
const SWEEP = END_ANGLE - START_ANGLE;
const CENTER = 100;
const TRACK_RADIUS = 78;

const STATUS_COLOR: Record<RiskStatus, string> = {
  ALLOW: "#78b79a",
  WARN: "#d5a766",
  LOCK_VERIFY: "#db817b",
};

const STATUS_LABEL: Record<RiskStatus, string> = {
  ALLOW: "Risk within policy",
  WARN: "Anomaly under review",
  LOCK_VERIFY: "Locked — verification required",
};

function angleForValue(value: number): number {
  const clamped = Math.max(0, Math.min(100, value));
  return START_ANGLE + (clamped / 100) * SWEEP;
}

function polarToCartesian(cx: number, cy: number, r: number, angleDeg: number) {
  const angleRad = ((angleDeg - 90) * Math.PI) / 180;
  return { x: cx + r * Math.cos(angleRad), y: cy + r * Math.sin(angleRad) };
}

function describeArc(r: number, startAngle: number, endAngle: number): string {
  const start = polarToCartesian(CENTER, CENTER, r, startAngle);
  const end = polarToCartesian(CENTER, CENTER, r, endAngle);
  const largeArcFlag = endAngle - startAngle <= 180 ? 0 : 1;
  return `M ${start.x} ${start.y} A ${r} ${r} 0 ${largeArcFlag} 1 ${end.x} ${end.y}`;
}

export default function TrustGauge({ score, status }: TrustGaugeProps) {
  const zoneBoundaries = useMemo(
    () => ({
      safeEnd: angleForValue(40),
      warnEnd: angleForValue(70),
    }),
    []
  );

  const ticks = useMemo(() => Array.from({ length: 11 }, (_, i) => i * 10), []);
  const needleAngle = angleForValue(score);
  const color = STATUS_COLOR[status];

  return (
    <div className="relative flex flex-col items-center">
      <svg viewBox="0 0 200 160" className="w-full max-w-[280px]">
        {/* Zone track */}
        <path d={describeArc(TRACK_RADIUS, START_ANGLE, zoneBoundaries.safeEnd)} fill="none" stroke="#294238" strokeWidth={10} strokeLinecap="butt" />
        <path d={describeArc(TRACK_RADIUS, zoneBoundaries.safeEnd, zoneBoundaries.warnEnd)} fill="none" stroke="#4a3f2c" strokeWidth={10} strokeLinecap="butt" />
        <path d={describeArc(TRACK_RADIUS, zoneBoundaries.warnEnd, END_ANGLE)} fill="none" stroke="#4a3232" strokeWidth={10} strokeLinecap="butt" />

        {/* Active fill up to current score, in the live status color */}
        <path
          d={describeArc(TRACK_RADIUS, START_ANGLE, needleAngle)}
          fill="none"
          stroke={color}
          strokeWidth={10}
          strokeLinecap="round"
          style={{ transition: "d 0.4s ease, stroke 0.3s ease" }}
        />

        {/* Tick marks */}
        {ticks.map((tick) => {
          const angle = angleForValue(tick);
          const inner = polarToCartesian(CENTER, CENTER, 62, angle);
          const outer = polarToCartesian(CENTER, CENTER, 70, angle);
          const isMajor = tick === 0 || tick === 50 || tick === 100;
          return (
            <line
              key={tick}
              x1={inner.x}
              y1={inner.y}
              x2={outer.x}
              y2={outer.y}
              stroke={isMajor ? "#7c8d98" : "#324450"}
              strokeWidth={isMajor ? 1.5 : 1}
            />
          );
        })}

        {/* Needle */}
        <g style={{ transition: "transform 0.4s ease" }}>
          <line
            x1={CENTER}
            y1={CENTER}
            x2={polarToCartesian(CENTER, CENTER, 58, needleAngle).x}
            y2={polarToCartesian(CENTER, CENTER, 58, needleAngle).y}
            stroke={color}
            strokeWidth={2.5}
            strokeLinecap="round"
          />
          <circle cx={CENTER} cy={CENTER} r={5} fill="#0f171d" stroke={color} strokeWidth={2} />
        </g>

        {/* Readout */}
        <text x={CENTER} y={128} textAnchor="middle" className="fill-mute" style={{ fontFamily: "'IBM Plex Sans', sans-serif", fontSize: 9 }}>
          Current risk score
        </text>
        <text
          x={CENTER}
          y={158}
          textAnchor="middle"
          className="tabular"
          style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 34, fontWeight: 600, fill: color }}
        >
          {Math.round(score)}
          <tspan style={{ fontSize: 14, fill: "#7c8d98" }}> /100</tspan>
        </text>
      </svg>
      <p className="mt-1 text-sm" style={{ color }}>
        {STATUS_LABEL[status]}
      </p>
    </div>
  );
}
