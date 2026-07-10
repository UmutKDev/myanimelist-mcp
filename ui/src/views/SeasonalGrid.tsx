import { useState } from "react";

import type { RankingEntry, SeasonalPayload } from "../mcp/types";
import { compactNumber, mediaType, seasonLabel } from "../lib/format";
import { useNav } from "../lib/nav";
import { CoverCard } from "../components/CoverCard";
import { EmptyState } from "../components/EmptyState";

/** Broadcast-season grid for get_seasonal_anime. */
export function SeasonalGrid({ payload }: { payload: SeasonalPayload }) {
  const { callTool } = useNav();
  const [entries, setEntries] = useState<RankingEntry[]>(payload.entries);
  const [hasMore, setHasMore] = useState(payload.has_more);
  const [loadingMore, setLoadingMore] = useState(false);

  async function loadMore() {
    setLoadingMore(true);
    try {
      const next = await callTool<SeasonalPayload>("get_seasonal_anime", {
        year: payload.year,
        season: payload.season,
        offset: payload.offset + entries.length,
      });
      setEntries((prev) => [...prev, ...next.entries]);
      setHasMore(next.has_more);
    } finally {
      setLoadingMore(false);
    }
  }

  if (entries.length === 0) {
    return <EmptyState message={`No anime found for ${payload.season} ${payload.year}.`} />;
  }

  return (
    <section className="view">
      <header className="view-header">
        <div className="eyebrow">Seasonal · {entries.length} title{entries.length === 1 ? "" : "s"}</div>
        <h1 className="display view-title">
          {seasonLabel(payload.season)} {payload.year}
        </h1>
      </header>

      <div className="card-grid">
        {entries.map((entry, i) => (
          <CoverCard
            key={entry.id}
            id={entry.id}
            kind="anime"
            title={entry.title}
            picture={entry.picture}
            index={i}
            badge={entry.mean != null && <span className="score-pill num">★ {entry.mean.toFixed(2)}</span>}
            meta={
              <>
                {mediaType(entry.media_type)}
                {entry.num_episodes ? ` · ${entry.num_episodes} ep` : ""}
                {entry.num_list_users ? ` · ${compactNumber(entry.num_list_users)} members` : ""}
              </>
            }
          />
        ))}
      </div>

      {hasMore && (
        <button className="btn btn-ghost load-more" onClick={loadMore} disabled={loadingMore}>
          {loadingMore ? "Loading…" : "Load more"}
        </button>
      )}
    </section>
  );
}
