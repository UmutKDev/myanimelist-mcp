import { useState } from "react";
import { motion, useReducedMotion } from "motion/react";

import type { DashboardPayload, StatsData } from "../mcp/types";
import { hueOf, label, statusColor } from "../lib/format";
import { useNav } from "../lib/nav";
import { CountUp } from "../components/CountUp";

function Bar({
  fraction,
  color,
  delay = 0,
}: {
  fraction: number;
  color: string;
  delay?: number;
}) {
  const reduced = useReducedMotion();
  return (
    <div className="bar-track">
      <motion.div
        className="bar-fill"
        style={{ background: color }}
        initial={reduced ? { width: `${fraction * 100}%` } : { width: 0 }}
        animate={{ width: `${fraction * 100}%` }}
        transition={{ duration: 0.7, ease: "easeOut", delay }}
      />
    </div>
  );
}

/** Profile + list statistics dashboard (get_my_profile / get_user_stats). */
export function Dashboard({ payload }: { payload: DashboardPayload }) {
  const { callTool } = useNav();
  const reduced = useReducedMotion();
  const [stats, setStats] = useState<StatsData | undefined>(payload.stats);
  const [loadingStats, setLoadingStats] = useState(false);
  const profile = payload.profile;

  async function loadStats() {
    setLoadingStats(true);
    try {
      const result = await callTool<{ stats?: StatsData } & StatsData>("get_user_stats", {});
      setStats(result.stats ?? (result as StatsData));
    } finally {
      setLoadingStats(false);
    }
  }

  const histogram = stats?.scores.histogram_1_to_10 ?? {};
  const histogramMax = Math.max(1, ...Object.values(histogram));
  const genreMax = Math.max(1, ...(stats?.top_genres ?? []).map((g) => g.count));
  const statusTotal = stats
    ? Math.max(1, Object.values(stats.status_distribution).reduce((a, b) => a + b, 0))
    : 1;
  const anime = profile?.anime_statistics ?? {};

  return (
    <section className="view">
      {profile && (
        <header className="profile-head">
          <div
            className="avatar-ring"
            style={{ background: `conic-gradient(from 200deg, var(--accent-1), var(--accent-2), var(--accent-1))` }}
          >
            <div className="avatar" style={{ background: `hsl(${hueOf(profile.name ?? "?")} 45% 30%)` }}>
              {profile.picture ? (
                <img src={profile.picture} alt={profile.name ?? "avatar"} />
              ) : (
                <span className="avatar-letter">{(profile.name ?? "?").charAt(0).toUpperCase()}</span>
              )}
            </div>
          </div>
          <div>
            <div className="eyebrow">MyAnimeList profile{profile.is_supporter ? " · Supporter" : ""}</div>
            <h1 className="display view-title">{profile.name ?? "Unknown"}</h1>
            <div className="profile-facts">
              {profile.location && <span>{profile.location}</span>}
              {profile.joined_at && <span>since {profile.joined_at.slice(0, 4)}</span>}
              {profile.time_zone && <span>{profile.time_zone}</span>}
            </div>
          </div>
        </header>
      )}

      <div className="tile-grid">
        <div className="tile glass">
          <span className="tile-value num">
            <CountUp value={stats?.total_entries ?? (anime.num_items as number) ?? 0} />
          </span>
          <span className="eyebrow">List entries</span>
        </div>
        <div className="tile glass">
          <span className="tile-value num">
            <CountUp
              value={stats?.episodes.total_episodes_watched ?? (anime.num_episodes as number) ?? 0}
            />
          </span>
          <span className="eyebrow">Episodes watched</span>
        </div>
        <div className="tile glass">
          <span className="tile-value num">
            <CountUp
              value={stats?.episodes.estimated_watch_days ?? (anime.num_days as number) ?? 0}
              decimals={1}
            />
          </span>
          <span className="eyebrow">Days of anime</span>
        </div>
        <div className="tile glass">
          <span className="tile-value num tile-gold">
            <CountUp value={stats?.scores.mean ?? (anime.mean_score as number) ?? 0} decimals={2} />
          </span>
          <span className="eyebrow">Mean score</span>
        </div>
      </div>

      {!stats && (
        <button className="btn btn-primary load-more" onClick={loadStats} disabled={loadingStats}>
          {loadingStats ? "Crunching your list…" : "Load full statistics"}
        </button>
      )}

      {stats && (
        <>
          <section className="panel glass">
            <div className="eyebrow panel-title">Status distribution</div>
            <div className="status-strip" role="img" aria-label="Status distribution">
              {Object.entries(stats.status_distribution).map(([status, count], i) => (
                <motion.div
                  key={status}
                  className="status-strip-seg"
                  style={{ background: statusColor(status) }}
                  initial={reduced ? false : { flexGrow: 0.0001 }}
                  animate={{ flexGrow: count / statusTotal }}
                  transition={{ duration: 0.7, ease: "easeOut", delay: i * 0.08 }}
                  title={`${label(status)}: ${count}`}
                />
              ))}
            </div>
            <div className="status-legend">
              {Object.entries(stats.status_distribution).map(([status, count]) => (
                <span key={status} className="legend-item">
                  <span className="status-dot" style={{ background: statusColor(status) }} />
                  {label(status)} <span className="num legend-count">{count}</span>
                </span>
              ))}
            </div>
          </section>

          <section className="panel glass">
            <div className="eyebrow panel-title">
              Score histogram · {stats.scores.scored_count} rated
            </div>
            <div className="histogram" role="img" aria-label="Score histogram 1 to 10">
              {Array.from({ length: 10 }, (_, i) => {
                const key = String(i + 1);
                const count = histogram[key] ?? 0;
                return (
                  <div key={key} className="hist-col">
                    <span className="num hist-count">{count || ""}</span>
                    <motion.div
                      className="hist-bar"
                      initial={reduced ? false : { height: 2 }}
                      animate={{ height: `${Math.max(2, (count / histogramMax) * 100)}%` }}
                      transition={{ duration: 0.6, ease: "easeOut", delay: 0.1 + i * 0.05 }}
                    />
                    <span className="num hist-label">{key}</span>
                  </div>
                );
              })}
            </div>
            {stats.community_comparison.avg_my_score_minus_mal_mean != null && (
              <p className="panel-note">
                You rate{" "}
                <strong className="num">
                  {Math.abs(stats.community_comparison.avg_my_score_minus_mal_mean).toFixed(2)}
                </strong>{" "}
                {stats.community_comparison.avg_my_score_minus_mal_mean >= 0 ? "above" : "below"}{" "}
                the MAL average across {stats.community_comparison.compared_entries} shared titles.
              </p>
            )}
          </section>

          <div className="panel-pair">
            <section className="panel glass">
              <div className="eyebrow panel-title">Top genres</div>
              <ul className="ranked-bars">
                {stats.top_genres.slice(0, 8).map((genre, i) => (
                  <li key={genre.name}>
                    <span className="ranked-name">{genre.name}</span>
                    <Bar
                      fraction={genre.count / genreMax}
                      color={`hsl(${hueOf(genre.name)} 65% 62%)`}
                      delay={i * 0.06}
                    />
                    <span className="num ranked-count">{genre.count}</span>
                    <span className="num ranked-score">
                      {genre.avg_my_score != null ? `★${genre.avg_my_score.toFixed(1)}` : ""}
                    </span>
                  </li>
                ))}
              </ul>
            </section>

            <section className="panel glass">
              <div className="eyebrow panel-title">Top studios</div>
              <ul className="ranked-bars">
                {stats.top_studios.slice(0, 8).map((studio, i) => (
                  <li key={studio.name}>
                    <span className="ranked-name">{studio.name}</span>
                    <Bar
                      fraction={studio.count / Math.max(1, stats.top_studios[0]?.count ?? 1)}
                      color="var(--accent-2)"
                      delay={i * 0.06}
                    />
                    <span className="num ranked-count">{studio.count}</span>
                    <span className="num ranked-score">
                      {studio.avg_my_score != null ? `★${studio.avg_my_score.toFixed(1)}` : ""}
                    </span>
                  </li>
                ))}
              </ul>
              <div className="eyebrow panel-title panel-title-gap">Release decades</div>
              <div className="decade-row">
                {Object.entries(stats.release_decades).map(([decade, count], i) => (
                  <div key={decade} className="decade">
                    <motion.div
                      className="decade-bar"
                      initial={reduced ? false : { height: 3 }}
                      animate={{
                        height: `${Math.max(
                          6,
                          (count / Math.max(1, ...Object.values(stats.release_decades))) * 56,
                        )}px`,
                      }}
                      transition={{ duration: 0.6, delay: 0.2 + i * 0.07 }}
                    />
                    <span className="num decade-label">{decade}</span>
                  </div>
                ))}
              </div>
            </section>
          </div>

          {stats.warning && <p className="panel-note panel-warning">{stats.warning}</p>}
        </>
      )}
    </section>
  );
}
