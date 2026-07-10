import { useState } from "react";

import type { SearchPayload, SearchResult } from "../mcp/types";
import { mediaType } from "../lib/format";
import { useNav } from "../lib/nav";
import { CoverCard } from "../components/CoverCard";
import { EmptyState } from "../components/EmptyState";

/** Cover grid for search_anime / search_manga / get_suggested_anime. */
export function SearchGrid({ payload }: { payload: SearchPayload }) {
  const { callTool } = useNav();
  const [results, setResults] = useState<SearchResult[]>(payload.results);
  const [hasMore, setHasMore] = useState(payload.has_more ?? false);
  const [loadingMore, setLoadingMore] = useState(false);

  const suggested = payload.suggested === true;
  const heading = suggested ? "Suggested for you" : payload.query ?? "Results";
  const eyebrow = suggested
    ? "MAL recommendations"
    : `${payload.kind} search · ${results.length} result${results.length === 1 ? "" : "s"}`;

  async function loadMore() {
    setLoadingMore(true);
    try {
      const next = await callTool<SearchPayload>("get_suggested_anime", {
        offset: (payload.offset ?? 0) + results.length,
      });
      setResults((prev) => [...prev, ...next.results]);
      setHasMore(next.has_more ?? false);
    } finally {
      setLoadingMore(false);
    }
  }

  if (results.length === 0) {
    return (
      <EmptyState
        message={suggested ? "MAL has no suggestions yet." : `Nothing found for “${payload.query}”.`}
        hint={suggested ? "Suggestions appear once your list has some history." : "Try a longer title fragment — MAL search needs ~3 characters."}
      />
    );
  }

  return (
    <section className="view">
      <header className="view-header">
        <div className="eyebrow">{eyebrow}</div>
        <h1 className="display view-title">{heading}</h1>
      </header>

      <div className="card-grid">
        {results.map((result, i) => (
          <CoverCard
            key={result.id}
            id={result.id}
            kind={payload.kind}
            title={result.title}
            picture={result.picture}
            index={i}
            badge={result.mean != null && <span className="score-pill num">★ {result.mean.toFixed(2)}</span>}
            meta={
              <>
                {result.year ?? "?"} · {mediaType(result.media_type)}
                {payload.kind === "anime" && result.num_episodes
                  ? ` · ${result.num_episodes} ep`
                  : payload.kind === "manga" && result.num_chapters
                    ? ` · ${result.num_chapters} ch`
                    : ""}
              </>
            }
          />
        ))}
      </div>

      {suggested && hasMore && (
        <button className="btn btn-ghost load-more" onClick={loadMore} disabled={loadingMore}>
          {loadingMore ? "Loading…" : "Load more"}
        </button>
      )}
    </section>
  );
}
