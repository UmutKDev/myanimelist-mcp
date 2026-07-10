import { motion, useReducedMotion } from "motion/react";

import type { ScheduleEntry, SchedulePayload } from "../mcp/types";
import { titleGradient } from "../lib/format";
import { useNav } from "../lib/nav";
import { EmptyState } from "../components/EmptyState";

const DAY_LABEL: Record<string, string> = {
  monday: "Mon",
  tuesday: "Tue",
  wednesday: "Wed",
  thursday: "Thu",
  friday: "Fri",
  saturday: "Sat",
  sunday: "Sun",
  unscheduled: "Unscheduled",
};

function ScheduleCard({ entry, index }: { entry: ScheduleEntry; index: number }) {
  const { openDetail } = useNav();
  const reduced = useReducedMotion();
  const total = entry.total_episodes || 0;
  const pct = total > 0 ? Math.min(100, (entry.episodes_watched / total) * 100) : 0;

  return (
    <motion.button
      className="sched-card"
      onClick={() => openDetail("anime", entry.id)}
      initial={reduced ? false : { opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: Math.min(index * 0.04, 0.3), duration: 0.3 }}
      whileHover={reduced ? undefined : { y: -3 }}
      whileTap={reduced ? undefined : { scale: 0.97 }}
      aria-label={`${entry.title}${entry.broadcast_time ? ` at ${entry.broadcast_time}` : ""}`}
    >
      <div className="sched-thumb" style={{ background: titleGradient(entry.title) }}>
        {entry.picture && (
          <img
            src={entry.picture}
            alt=""
            loading="lazy"
            onError={(e) => (e.currentTarget.style.display = "none")}
          />
        )}
        {entry.broadcast_time && <span className="sched-time num">{entry.broadcast_time}</span>}
      </div>
      <div className="sched-title" title={entry.title}>
        {entry.title}
      </div>
      <div className="sched-progress">
        <div className="sched-progress-track">
          <div className="sched-progress-fill" style={{ width: `${pct}%` }} />
        </div>
        <span className="num sched-progress-label">
          {entry.episodes_watched}/{total || "?"}
        </span>
      </div>
    </motion.button>
  );
}

/** Personal weekly airing calendar (get_weekly_schedule). */
export function ScheduleView({ payload }: { payload: SchedulePayload }) {
  const reduced = useReducedMotion();

  if (payload.total === 0) {
    return (
      <EmptyState
        message="Nothing from your watching list airs this week."
        hint="Add some currently-airing shows to your MAL 'watching' list to fill the calendar."
      />
    );
  }

  const weekdays = payload.days.filter((d) => d.day !== "unscheduled");
  const unscheduled = payload.days.find((d) => d.day === "unscheduled");

  return (
    <section className="view schedule">
      <header className="view-header">
        <div className="eyebrow">
          Weekly airing · {payload.total} show{payload.total === 1 ? "" : "s"} · times in{" "}
          {payload.timezone}
        </div>
        <h1 className="display view-title">This week</h1>
      </header>

      <div className="week-grid">
        {weekdays.map((d, ci) => {
          const today = d.day === payload.today;
          return (
            <motion.div
              key={d.day}
              className={`day-col${today ? " is-today" : ""}`}
              initial={reduced ? false : { opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: Math.min(ci * 0.05, 0.4), duration: 0.3 }}
            >
              <div className="day-head">
                <span>{DAY_LABEL[d.day]}</span>
                {today && <span className="today-pill">Today</span>}
              </div>
              {d.entries.length > 0 ? (
                <div className="day-cards">
                  {d.entries.map((e, i) => (
                    <ScheduleCard key={e.id} entry={e} index={i} />
                  ))}
                </div>
              ) : (
                <div className="day-empty">·</div>
              )}
            </motion.div>
          );
        })}
      </div>

      {unscheduled && unscheduled.entries.length > 0 && (
        <section className="unscheduled-strip">
          <div className="eyebrow">No fixed broadcast slot</div>
          <div className="unscheduled-cards">
            {unscheduled.entries.map((e, i) => (
              <ScheduleCard key={e.id} entry={e} index={i} />
            ))}
          </div>
        </section>
      )}
    </section>
  );
}
