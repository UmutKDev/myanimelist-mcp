import { motion, useReducedMotion } from "motion/react";

export function GenreChips({ genres, limit = 6 }: { genres: string[]; limit?: number }) {
  const reduced = useReducedMotion();
  const shown = genres.slice(0, limit);
  if (shown.length === 0) return null;
  return (
    <div className="genre-chips">
      {shown.map((genre, i) => (
        <motion.span
          key={genre}
          className="chip"
          initial={reduced ? false : { opacity: 0, scale: 0.85 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ delay: 0.15 + i * 0.05, duration: 0.25 }}
        >
          {genre}
        </motion.span>
      ))}
      {genres.length > limit && <span className="chip chip-more">+{genres.length - limit}</span>}
    </div>
  );
}
