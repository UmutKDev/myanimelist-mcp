import { useMemo, useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";

import type { ListEntry, ListPayload, MyListStatus } from "../mcp/types";
import {
  ANIME_STATUSES,
  MANGA_STATUSES,
  mediaType,
  statusColor,
  titleGradient,
} from "../lib/format";
import { useNav } from "../lib/nav";
import { Toolbar } from "../components/Toolbar";
import { StatusBadge } from "../components/StatusBadge";
import { ProgressBar } from "../components/ProgressBar";
import { EntryEditor } from "../components/EntryEditor";
import { EmptyState } from "../components/EmptyState";

const SORTS = [
  { value: "updated", text: "Recently updated" },
  { value: "score", text: "My score" },
  { value: "title", text: "Title A–Z" },
  { value: "year", text: "Year" },
  { value: "mean", text: "MAL score" },
];

function progressOf(entry: ListEntry, kind: "anime" | "manga"): [number, number] {
  return kind === "anime"
    ? [entry.episodes_watched ?? 0, entry.total_episodes ?? 0]
    : [entry.chapters_read ?? 0, entry.total_chapters ?? 0];
}

/** Personal list browser: status tabs, client-side filter/sort, inline editing. */
export function ListBrowser({ payload }: { payload: ListPayload }) {
  const { callTool, openDetail } = useNav();
  const reduced = useReducedMotion();
  const statuses = payload.kind === "anime" ? ANIME_STATUSES : MANGA_STATUSES;

  const [entries, setEntries] = useState<ListEntry[]>(payload.entries);
  const [hasMore, setHasMore] = useState(payload.has_more);
  const [loadingMore, setLoadingMore] = useState(false);
  const [statusFilter, setStatusFilter] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState("updated");
  const [expandedId, setExpandedId] = useState<number | null>(null);

  const statusCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const entry of entries) {
      const key = entry.my_status ?? "unknown";
      counts[key] = (counts[key] ?? 0) + 1;
    }
    return counts;
  }, [entries]);

  const visible = useMemo(() => {
    let list = entries;
    if (statusFilter) list = list.filter((e) => e.my_status === statusFilter);
    if (search.trim()) {
      const needle = search.trim().toLowerCase();
      list = list.filter((e) => e.title.toLowerCase().includes(needle));
    }
    const sorted = [...list];
    switch (sort) {
      case "score":
        sorted.sort((a, b) => b.my_score - a.my_score);
        break;
      case "title":
        sorted.sort((a, b) => a.title.localeCompare(b.title));
        break;
      case "year":
        sorted.sort((a, b) => (b.year ?? 0) - (a.year ?? 0));
        break;
      case "mean":
        sorted.sort((a, b) => (b.mal_mean ?? 0) - (a.mal_mean ?? 0));
        break;
      default:
        sorted.sort((a, b) => (b.updated_at ?? "").localeCompare(a.updated_at ?? ""));
    }
    return sorted;
  }, [entries, statusFilter, search, sort]);

  async function loadMore() {
    setLoadingMore(true);
    try {
      const tool = payload.user_name
        ? `get_user_${payload.kind}_list`
        : `get_my_${payload.kind}_list`;
      const args: Record<string, unknown> = { offset: payload.offset + entries.length };
      if (payload.user_name) args.user_name = payload.user_name;
      const next = await callTool<ListPayload>(tool, args);
      setEntries((prev) => [...prev, ...next.entries]);
      setHasMore(next.has_more);
    } finally {
      setLoadingMore(false);
    }
  }

  function applySaved(id: number, saved: MyListStatus) {
    setEntries((prev) =>
      prev.map((entry) =>
        entry.id === id
          ? {
              ...entry,
              my_status: saved.status ?? entry.my_status,
              my_score: saved.score ?? entry.my_score,
              episodes_watched: saved.num_episodes_watched ?? entry.episodes_watched,
              chapters_read: saved.num_chapters_read ?? entry.chapters_read,
              updated_at: new Date().toISOString(),
            }
          : entry,
      ),
    );
  }

  const owner = payload.user_name ? `${payload.user_name}'s` : "My";

  return (
    <section className="view">
      <header className="view-header">
        <div className="eyebrow">
          {payload.editable ? "Personal list" : "Public list"} · {entries.length} loaded
          {hasMore ? " · more available" : ""}
        </div>
        <h1 className="display view-title">
          {owner} {payload.kind} list
        </h1>
      </header>

      <Toolbar
        statuses={statuses}
        statusCounts={statusCounts}
        activeStatus={statusFilter}
        onStatus={setStatusFilter}
        search={search}
        onSearch={setSearch}
        sort={sort}
        sortOptions={SORTS}
        onSort={setSort}
      />

      {visible.length === 0 ? (
        <EmptyState
          message="No entries match."
          hint={search ? "Try a different title filter." : "This status group is empty."}
        />
      ) : (
        <ul className="list-rows">
          {visible.map((entry, i) => {
            const [current, total] = progressOf(entry, payload.kind);
            const expanded = expandedId === entry.id;
            return (
              <motion.li
                key={entry.id}
                layout={!reduced}
                initial={reduced ? false : { opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: Math.min(i * 0.03, 0.4), duration: 0.3 }}
                className={`list-row glass${expanded ? " is-expanded" : ""}`}
              >
                <div className="list-row-main">
                  <button
                    className="list-thumb"
                    style={{ background: titleGradient(entry.title) }}
                    onClick={() => openDetail(payload.kind, entry.id)}
                    aria-label={`Open ${entry.title}`}
                  >
                    {entry.picture && (
                      <img
                        src={entry.picture}
                        alt=""
                        loading="lazy"
                        onError={(e) => (e.currentTarget.style.display = "none")}
                      />
                    )}
                  </button>
                  <div className="list-body">
                    <button
                      className="list-title"
                      onClick={() => openDetail(payload.kind, entry.id)}
                    >
                      {entry.title}
                    </button>
                    <div className="list-meta">
                      {entry.year ?? "?"} · {mediaType(entry.media_type)}
                      {entry.genres.length > 0 ? ` · ${entry.genres.slice(0, 3).join(", ")}` : ""}
                    </div>
                    <div className="list-progress">
                      <StatusBadge status={entry.my_status} />
                      <ProgressBar
                        current={current}
                        total={total}
                        color={statusColor(entry.my_status)}
                      />
                    </div>
                  </div>
                  <div className="list-scores">
                    <span
                      className="num list-my-score"
                      style={{ color: entry.my_score ? "var(--gold)" : "var(--text-faint)" }}
                      title="My score"
                    >
                      {entry.my_score || "–"}
                    </span>
                    <span className="num list-mean" title="MAL community score">
                      {entry.mal_mean != null ? `★ ${entry.mal_mean.toFixed(2)}` : "–"}
                    </span>
                  </div>
                  {payload.editable && (
                    <button
                      className="btn btn-ghost list-edit"
                      aria-expanded={expanded}
                      onClick={() => setExpandedId(expanded ? null : entry.id)}
                    >
                      {expanded ? "Close" : "Edit"}
                    </button>
                  )}
                </div>

                <AnimatePresence>
                  {expanded && payload.editable && (
                    <motion.div
                      className="list-editor"
                      initial={reduced ? false : { opacity: 0, height: 0 }}
                      animate={{ opacity: 1, height: "auto" }}
                      exit={{ opacity: 0, height: 0 }}
                      transition={{ duration: 0.28, ease: "easeOut" }}
                    >
                      <EntryEditor
                        kind={payload.kind}
                        id={entry.id}
                        title={entry.title}
                        current={{
                          status: entry.my_status ?? undefined,
                          score: entry.my_score,
                          num_episodes_watched: entry.episodes_watched,
                          num_chapters_read: entry.chapters_read,
                        }}
                        totalUnits={total}
                        onSaved={(saved) => applySaved(entry.id, saved)}
                        onRemoved={() => {
                          setEntries((prev) => prev.filter((e) => e.id !== entry.id));
                          setExpandedId(null);
                        }}
                      />
                    </motion.div>
                  )}
                </AnimatePresence>
              </motion.li>
            );
          })}
        </ul>
      )}

      {hasMore && (
        <button className="btn btn-ghost load-more" onClick={loadMore} disabled={loadingMore}>
          {loadingMore ? "Loading…" : "Load more"}
        </button>
      )}
    </section>
  );
}
