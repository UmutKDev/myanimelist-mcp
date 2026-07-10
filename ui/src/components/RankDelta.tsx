import { motion, useReducedMotion } from "motion/react";

/** Rank movement vs the previous ranking snapshot (MAL often omits it). */
export function RankDelta({ rank, previous }: { rank: number | null; previous: number | null }) {
  const reduced = useReducedMotion();
  if (rank == null || previous == null) {
    return (
      <span className="delta delta-flat" aria-label="no previous rank">
        –
      </span>
    );
  }
  const diff = previous - rank; // positive = climbed
  if (diff === 0) {
    return (
      <span className="delta delta-flat" aria-label="unchanged">
        =
      </span>
    );
  }
  const up = diff > 0;
  return (
    <motion.span
      className={`delta ${up ? "delta-up" : "delta-down"}`}
      initial={reduced ? false : { opacity: 0, y: up ? 8 : -8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, ease: "easeOut" }}
      aria-label={`${up ? "up" : "down"} ${Math.abs(diff)}`}
    >
      {up ? "▲" : "▼"}
      {Math.abs(diff)}
    </motion.span>
  );
}
