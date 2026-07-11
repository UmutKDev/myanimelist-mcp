import { useId } from "react";
import { motion, useReducedMotion } from "motion/react";

import { CountUp } from "./CountUp";

/** Community score as a gradient ring that sweeps from 0 to the score. */
export function ScoreRing({
  value,
  max = 10,
  size = 86,
  label = "score",
}: {
  value: number | null;
  max?: number;
  size?: number;
  label?: string;
}) {
  const gradientId = useId();
  const reduced = useReducedMotion();
  const stroke = 6;
  const radius = (size - stroke) / 2;
  const circumference = 2 * Math.PI * radius;
  const fraction = value ? Math.min(1, value / max) : 0;
  const target = circumference * (1 - fraction);

  return (
    <div className="score-ring" style={{ width: size, height: size }} role="img" aria-label={`${label}: ${value ?? "unknown"}`}>
      <svg width={size} height={size}>
        <defs>
          <linearGradient id={gradientId} x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor="var(--accent-1)" />
            <stop offset="100%" stopColor="var(--gold)" />
          </linearGradient>
        </defs>
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="var(--line)"
          strokeWidth={stroke}
        />
        <motion.circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke={`url(#${gradientId})`}
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={circumference}
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
          initial={{ strokeDashoffset: reduced ? target : circumference }}
          animate={{ strokeDashoffset: target }}
          transition={{ duration: 1.2, ease: [0.22, 1, 0.36, 1], delay: 0.15 }}
        />
      </svg>
      <div className="score-ring-center">
        {value != null ? (
          <CountUp value={value} decimals={value % 1 === 0 ? 0 : 2} duration={1.2} />
        ) : (
          <span className="num">–</span>
        )}
        <span className="score-ring-label">{label}</span>
      </div>
    </div>
  );
}
