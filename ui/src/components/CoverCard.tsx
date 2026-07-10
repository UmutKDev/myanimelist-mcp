import { useState, type ReactNode } from "react";
import { motion, useReducedMotion } from "motion/react";

import type { Kind } from "../mcp/types";
import { titleGlow, titleGradient } from "../lib/format";
import { useNav } from "../lib/nav";

/** Cover-forward grid card; the whole card opens the title's detail view. */
export function CoverCard({
  id,
  kind,
  title,
  picture,
  badge,
  meta,
  index = 0,
}: {
  id: number;
  kind: Kind;
  title: string;
  picture: string | null;
  /** Overlaid top-right on the cover (e.g. a score). */
  badge?: ReactNode;
  /** Line under the title (year · type · length). */
  meta?: ReactNode;
  index?: number;
}) {
  const { openDetail } = useNav();
  const reduced = useReducedMotion();
  const [loaded, setLoaded] = useState(false);

  return (
    <motion.button
      className="cover-card"
      style={{ "--glow": titleGlow(title) } as React.CSSProperties}
      onClick={() => openDetail(kind, id)}
      initial={reduced ? false : { opacity: 0, y: 18 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: Math.min(index * 0.04, 0.5), duration: 0.35, ease: "easeOut" }}
      whileHover={reduced ? undefined : { y: -5 }}
      whileTap={reduced ? undefined : { scale: 0.97 }}
      aria-label={`Open ${title}`}
    >
      <motion.div
        className="cover-frame"
        layoutId={`cover-${kind}-${id}`}
        style={{ background: titleGradient(title) }}
      >
        {picture && (
          <img
            src={picture}
            alt=""
            loading="lazy"
            className={`cover-img${loaded ? " is-loaded" : ""}`}
            onLoad={() => setLoaded(true)}
            onError={(e) => (e.currentTarget.style.display = "none")}
          />
        )}
        {badge && <div className="cover-badge">{badge}</div>}
      </motion.div>
      <div className="cover-title" title={title}>
        {title}
      </div>
      {meta && <div className="cover-meta">{meta}</div>}
    </motion.button>
  );
}
