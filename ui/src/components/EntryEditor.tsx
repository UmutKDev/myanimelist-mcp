import { useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";

import type { Kind, MyListStatus, UpdateResult } from "../mcp/types";
import { ANIME_STATUSES, MANGA_STATUSES, label, statusColor } from "../lib/format";
import { useNav } from "../lib/nav";

type Phase = "idle" | "saving" | "saved" | "removing";

/** Inline list editor: status, score, and progress, saved through the server tools. */
export function EntryEditor({
  kind,
  id,
  title,
  current,
  totalUnits = 0,
  onSaved,
  onRemoved,
}: {
  kind: Kind;
  id: number;
  title: string;
  current: MyListStatus | null | undefined;
  /** Episode or chapter count; 0 = unknown. */
  totalUnits?: number;
  onSaved?: (status: MyListStatus) => void;
  onRemoved?: () => void;
}) {
  const { callTool, noteToModel } = useNav();
  const reduced = useReducedMotion();
  const statuses = kind === "anime" ? ANIME_STATUSES : MANGA_STATUSES;
  const currentProgress =
    (kind === "anime" ? current?.num_episodes_watched : current?.num_chapters_read) ?? 0;

  const [status, setStatus] = useState<string>(current?.status ?? statuses[0]);
  const [score, setScore] = useState<number>(current?.score ?? 0);
  const [progress, setProgress] = useState<number>(currentProgress);
  const [phase, setPhase] = useState<Phase>("idle");
  const [confirmRemove, setConfirmRemove] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const onList = current != null;
  const dirty =
    !onList ||
    status !== (current?.status ?? "") ||
    score !== (current?.score ?? 0) ||
    progress !== currentProgress;

  const clampProgress = (value: number) =>
    Math.max(0, totalUnits > 0 ? Math.min(totalUnits, value) : value);

  async function save() {
    setPhase("saving");
    setError(null);
    const args: Record<string, unknown> =
      kind === "anime"
        ? { anime_id: id, status, score, num_watched_episodes: progress }
        : { manga_id: id, status, score, num_chapters_read: progress };
    try {
      const result = await callTool<UpdateResult>(`update_my_${kind}_entry`, args);
      setPhase("saved");
      noteToModel(
        `User set "${title}" to ${label(status)} (score ${score || "unrated"}, ` +
          `progress ${progress}) via the app.`,
      );
      onSaved?.(result.my_list_status ?? { status, score });
      setTimeout(() => setPhase("idle"), 1600);
    } catch (err) {
      setPhase("idle");
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function remove() {
    if (!confirmRemove) {
      setConfirmRemove(true);
      setTimeout(() => setConfirmRemove(false), 3200);
      return;
    }
    setPhase("removing");
    setError(null);
    try {
      await callTool(`delete_my_${kind}_entry`, kind === "anime" ? { anime_id: id } : { manga_id: id });
      noteToModel(`User removed "${title}" from their ${kind} list via the app.`);
      onRemoved?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setPhase("idle");
      setConfirmRemove(false);
    }
  }

  return (
    <div className="entry-editor" aria-label={`Edit list entry for ${title}`}>
      <div className="editor-row">
        <span className="eyebrow">Status</span>
        <div className="segmented" role="radiogroup" aria-label="Status">
          {statuses.map((option) => (
            <button
              key={option}
              role="radio"
              aria-checked={status === option}
              className={`segment${status === option ? " is-active" : ""}`}
              style={status === option ? { color: statusColor(option) } : undefined}
              onClick={() => setStatus(option)}
            >
              {label(option)}
            </button>
          ))}
        </div>
      </div>

      <div className="editor-row editor-row-controls">
        <div className="stepper-group">
          <span className="eyebrow">Score</span>
          <div className="stepper">
            <button aria-label="Lower score" onClick={() => setScore((s) => Math.max(0, s - 1))}>
              −
            </button>
            <span className="num stepper-value" style={{ color: score ? "var(--gold)" : "var(--text-dim)" }}>
              {score || "–"}
            </span>
            <button aria-label="Raise score" onClick={() => setScore((s) => Math.min(10, s + 1))}>
              +
            </button>
          </div>
        </div>

        <div className="stepper-group">
          <span className="eyebrow">{kind === "anime" ? "Episodes" : "Chapters"}</span>
          <div className="stepper">
            <button aria-label="Decrease progress" onClick={() => setProgress((p) => clampProgress(p - 1))}>
              −
            </button>
            <span className="num stepper-value">
              {progress}
              <span className="stepper-total">/{totalUnits || "?"}</span>
            </span>
            <button aria-label="Increase progress" onClick={() => setProgress((p) => clampProgress(p + 1))}>
              +
            </button>
          </div>
        </div>

        <div className="editor-actions">
          <motion.button
            className="btn btn-primary"
            disabled={phase !== "idle" || !dirty}
            onClick={save}
            whileTap={reduced ? undefined : { scale: 0.96 }}
          >
            {phase === "saving" ? "Saving…" : onList ? "Save changes" : "Add to list"}
          </motion.button>
          {onList && (
            <button
              className={`btn btn-danger${confirmRemove ? " is-armed" : ""}`}
              disabled={phase === "removing"}
              onClick={remove}
            >
              {phase === "removing" ? "Removing…" : confirmRemove ? "Really remove?" : "Remove"}
            </button>
          )}
        </div>
      </div>

      <AnimatePresence>
        {phase === "saved" && (
          <motion.div
            className="save-pulse"
            initial={{ opacity: 0, scale: 0.8 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.3, ease: "easeOut" }}
            role="status"
          >
            ✓ Saved
          </motion.div>
        )}
        {error && (
          <motion.div
            className="editor-error"
            role="alert"
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
          >
            {error}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
