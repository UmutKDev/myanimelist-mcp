import { motion, useReducedMotion } from "motion/react";

/** Watched/read progress; total of 0 means MAL doesn't know the length. */
export function ProgressBar({
  current,
  total,
  color = "var(--accent-2)",
}: {
  current: number;
  total: number;
  color?: string;
}) {
  const reduced = useReducedMotion();
  const known = total > 0;
  const pct = known ? Math.min(100, (current / total) * 100) : current > 0 ? 100 : 0;

  return (
    <div className="progress-wrap">
      <div className="progress" role="progressbar" aria-valuenow={current} aria-valuemax={known ? total : undefined}>
        <motion.div
          className="progress-fill"
          style={{ background: color, opacity: known ? 1 : 0.35 }}
          initial={reduced ? { width: `${pct}%` } : { width: 0 }}
          animate={{ width: `${pct}%` }}
          transition={{ duration: 0.8, ease: "easeOut", delay: 0.1 }}
        />
      </div>
      <span className="progress-label num">
        {current}/{known ? total : "?"}
      </span>
    </div>
  );
}
