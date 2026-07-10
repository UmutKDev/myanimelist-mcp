import { useState } from "react";
import { motion, useReducedMotion } from "motion/react";

import type { RankingEntry, RankingPayload } from "../mcp/types";
import { compactNumber, label, mediaType, titleGradient } from "../lib/format";
import { useNav } from "../lib/nav";
import { RankDelta } from "../components/RankDelta";
import { EmptyState } from "../components/EmptyState";

/** MAL official rankings as rows with movement indicators. */
export function Rankings({ payload }: { payload: RankingPayload }) {
  const { callTool, openDetail } = useNav();
  const reduced = useReducedMotion();
  const [entries, setEntries] = useState<RankingEntry[]>(payload.entries);
  const [hasMore, setHasMore] = useState(payload.has_more);
  const [loadingMore, setLoadingMore] = useState(false);

  async function loadMore() {
    setLoadingMore(true);
    try {
      const next = await callTool<RankingPayload>(`get_${payload.kind}_ranking`, {
        ranking_type: payload.ranking_type,
        offset: payload.offset + entries.length,
      });
      setEntries((prev) => [...prev, ...next.entries]);
      setHasMore(next.has_more);
    } finally {
      setLoadingMore(false);
    }
  }

  if (entries.length === 0) {
    return <EmptyState message="This ranking is empty." />;
  }

  return (
    <section className="view">
      <header className="view-header">
        <div className="eyebrow">
          MAL {payload.kind} ranking · {label(payload.ranking_type)}
        </div>
        <h1 className="display view-title">
          Top {payload.kind === "anime" ? "Anime" : "Manga"}
        </h1>
      </header>

      <ol className="rank-list">
        {entries.map((entry, i) => (
          <motion.li
            key={entry.id}
            initial={reduced ? false : { opacity: 0, x: -16 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ delay: Math.min(i * 0.05, 0.6), duration: 0.32, ease: "easeOut" }}
          >
            <button className="rank-row" onClick={() => openDetail(payload.kind, entry.id)}>
              <span className={`rank-num num${(entry.rank ?? 99) <= 3 ? " rank-top" : ""}`}>
                {entry.rank ?? "–"}
              </span>
              <RankDelta rank={entry.rank} previous={entry.previous_rank} />
              <span className="rank-thumb" style={{ background: titleGradient(entry.title) }}>
                {entry.picture && (
                  <img
                    src={entry.picture}
                    alt=""
                    loading="lazy"
                    onError={(e) => (e.currentTarget.style.display = "none")}
                  />
                )}
              </span>
              <span className="rank-body">
                <span className="rank-title">{entry.title}</span>
                <span className="rank-meta">
                  {entry.year ?? "?"} · {mediaType(entry.media_type)}
                  {payload.kind === "anime" && entry.num_episodes ? ` · ${entry.num_episodes} ep` : ""}
                  {payload.kind === "manga" && entry.num_chapters ? ` · ${entry.num_chapters} ch` : ""}
                  {entry.genres.length > 0 ? ` · ${entry.genres.slice(0, 3).join(", ")}` : ""}
                </span>
              </span>
              <span className="rank-score num">{entry.mean != null ? `★ ${entry.mean.toFixed(2)}` : "–"}</span>
              <span className="rank-members num">{compactNumber(entry.num_list_users)}</span>
            </button>
          </motion.li>
        ))}
      </ol>

      {hasMore && (
        <button className="btn btn-ghost load-more" onClick={loadMore} disabled={loadingMore}>
          {loadingMore ? "Loading…" : "Load more"}
        </button>
      )}
    </section>
  );
}
