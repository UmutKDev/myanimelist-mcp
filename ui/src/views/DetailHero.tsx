import { useState } from "react";
import { motion, useReducedMotion } from "motion/react";

import type { DetailPayload } from "../mcp/types";
import { compactNumber, label, mediaType, titleGradient } from "../lib/format";
import { useNav } from "../lib/nav";
import { ScoreRing } from "../components/ScoreRing";
import { GenreChips } from "../components/GenreChips";
import { EntryEditor } from "../components/EntryEditor";
import { CountUp } from "../components/CountUp";
import { StatusBadge } from "../components/StatusBadge";

const SYNOPSIS_CLAMP = 420;

/** Cinematic hero page for one title, with inline list management. */
export function DetailHero({ payload }: { payload: DetailPayload }) {
  const { back, canGoBack, openOnMal, openDetail, requestFullscreen, hostCtx } = useNav();
  const reduced = useReducedMotion();
  const [synopsisOpen, setSynopsisOpen] = useState(false);
  const [listStatus, setListStatus] = useState(payload.my_list_status ?? null);
  const [removed, setRemoved] = useState(false);

  const backdrop = payload.picture_large ?? payload.picture;
  const status = payload.kind === "anime" ? payload.airing_status : payload.publishing_status;
  const lengthText =
    payload.kind === "anime"
      ? payload.num_episodes
        ? `${payload.num_episodes} episodes`
        : "Episodes unknown"
      : `${payload.num_chapters || "?"} chapters · ${payload.num_volumes || "?"} volumes`;
  const credits =
    payload.kind === "anime" ? (payload.studios ?? []) : (payload.authors ?? []);
  const related =
    (payload.kind === "anime" ? payload.related_anime : payload.related_manga) ?? [];
  const synopsis = payload.synopsis ?? "";
  const needsClamp = synopsis.length > SYNOPSIS_CLAMP;
  const canFullscreen = (hostCtx?.availableDisplayModes ?? []).includes("fullscreen");

  return (
    <article className="detail">
      <div className="detail-backdrop" aria-hidden="true">
        {backdrop && (
          <motion.img
            src={backdrop}
            alt=""
            initial={reduced ? { scale: 1.08 } : { scale: 1.04 }}
            animate={reduced ? { scale: 1.08 } : { scale: 1.16, x: -14 }}
            transition={{ duration: 36, ease: "linear" }}
          />
        )}
        <div className="detail-backdrop-veil" />
      </div>

      <div className="detail-topbar">
        {canGoBack && (
          <button className="btn btn-ghost" onClick={back}>
            ← Back
          </button>
        )}
        <div className="detail-topbar-spacer" />
        {canFullscreen && (
          <button className="btn btn-ghost" onClick={requestFullscreen} aria-label="Toggle fullscreen">
            ⤢ Fullscreen
          </button>
        )}
        <button className="btn btn-ghost" onClick={() => openOnMal(payload.kind, payload.id)}>
          Open on MAL ↗
        </button>
      </div>

      <div className="detail-hero">
        <motion.div
          className="detail-cover"
          layoutId={`cover-${payload.kind}-${payload.id}`}
          style={{ background: titleGradient(payload.title) }}
        >
          {(payload.picture_large ?? payload.picture) && (
            <img
              src={payload.picture_large ?? payload.picture ?? undefined}
              alt={payload.title}
              onError={(e) => (e.currentTarget.style.display = "none")}
            />
          )}
        </motion.div>

        <div className="detail-info">
          <div className="eyebrow">
            {payload.kind} · {payload.year ?? "?"} · {mediaType(payload.media_type)} ·{" "}
            {label(status)}
          </div>
          <motion.h1
            className="display detail-title"
            initial={reduced ? false : { opacity: 0, y: 14 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.4, ease: "easeOut", delay: 0.08 }}
          >
            {payload.title}
          </motion.h1>
          {payload.alternative_titles?.en && payload.alternative_titles.en !== payload.title && (
            <div className="detail-alt">{payload.alternative_titles.en}</div>
          )}
          {payload.alternative_titles?.ja && (
            <div className="detail-alt detail-alt-ja">{payload.alternative_titles.ja}</div>
          )}

          <GenreChips genres={payload.genres} limit={8} />

          <div className="detail-stats">
            <ScoreRing value={payload.mean} label="MAL mean" />
            <div className="stat-block">
              <span className="stat-value num">
                {payload.rank != null ? <>#<CountUp value={payload.rank} /></> : "–"}
              </span>
              <span className="eyebrow">Rank</span>
            </div>
            <div className="stat-block">
              <span className="stat-value num">
                {payload.popularity != null ? <>#<CountUp value={payload.popularity} /></> : "–"}
              </span>
              <span className="eyebrow">Popularity</span>
            </div>
            <div className="stat-block">
              <span className="stat-value num">{compactNumber(payload.num_list_users)}</span>
              <span className="eyebrow">Members</span>
            </div>
            <div className="stat-block">
              <span className="stat-value">{lengthText}</span>
              <span className="eyebrow">
                {credits.length > 0
                  ? credits.slice(0, 2).join(", ")
                  : payload.kind === "anime"
                    ? "Studio unknown"
                    : "Author unknown"}
              </span>
            </div>
          </div>

          {synopsis && (
            <div className="detail-synopsis">
              <p>
                {needsClamp && !synopsisOpen ? `${synopsis.slice(0, SYNOPSIS_CLAMP)}…` : synopsis}
              </p>
              {needsClamp && (
                <button className="btn-link" onClick={() => setSynopsisOpen((open) => !open)}>
                  {synopsisOpen ? "Show less" : "Read more"}
                </button>
              )}
            </div>
          )}
        </div>
      </div>

      <motion.section
        className="detail-panel glass"
        initial={reduced ? false : { opacity: 0, y: 18 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4, ease: "easeOut", delay: 0.2 }}
        aria-label="My list entry"
      >
        <div className="panel-head">
          <span className="eyebrow">My list</span>
          {removed ? (
            <span className="detail-removed">Removed from list</span>
          ) : (
            listStatus && <StatusBadge status={listStatus.status} />
          )}
        </div>
        {!removed && (
          <EntryEditor
            kind={payload.kind}
            id={payload.id}
            title={payload.title}
            current={listStatus}
            totalUnits={
              payload.kind === "anime" ? payload.num_episodes ?? 0 : payload.num_chapters ?? 0
            }
            onSaved={(saved) => setListStatus(saved)}
            onRemoved={() => {
              setListStatus(null);
              setRemoved(true);
            }}
          />
        )}
        {removed && (
          <button className="btn btn-ghost" onClick={() => setRemoved(false)}>
            Add it back
          </button>
        )}
      </motion.section>

      {related.length > 0 && (
        <section className="detail-rail">
          <div className="eyebrow rail-title">Related</div>
          <div className="rail">
            {related.map((title) => (
              <button
                key={`${title.relation_type}-${title.id}`}
                className="rail-item glass"
                onClick={() => openDetail(payload.kind, title.id)}
              >
                <span className="rail-item-title">{title.title}</span>
                <span className="rail-item-sub">{label(title.relation_type)}</span>
              </button>
            ))}
          </div>
        </section>
      )}

      {(payload.recommendations?.length ?? 0) > 0 && (
        <section className="detail-rail">
          <div className="eyebrow rail-title">The community also recommends</div>
          <div className="rail">
            {payload.recommendations!.map((rec) => (
              <button
                key={rec.id}
                className="rail-item glass"
                onClick={() => openDetail(payload.kind, rec.id)}
              >
                <span className="rail-item-title">{rec.title}</span>
                <span className="rail-item-sub num">{rec.num_recommendations} votes</span>
              </button>
            ))}
          </div>
        </section>
      )}
    </article>
  );
}
