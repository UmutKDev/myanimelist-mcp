import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence, LayoutGroup, motion } from "motion/react";
import type { McpUiHostContext } from "@modelcontextprotocol/ext-apps";

import {
  applyHostContext,
  callTool as hostCallTool,
  isEmbedded,
  noteToModel,
  openOnMal,
  start,
  toggleFullscreen,
} from "./mcp/bridge";
import type { DetailPayload, Kind, ViewPayload } from "./mcp/types";
import { NavContext, type Nav } from "./lib/nav";
import { devCallTool, devPayload } from "./dev/devHost";
import { SearchGrid } from "./views/SearchGrid";
import { ListBrowser } from "./views/ListBrowser";
import { DetailHero } from "./views/DetailHero";
import { Rankings } from "./views/Rankings";
import { SeasonalGrid } from "./views/SeasonalGrid";
import { Dashboard } from "./views/Dashboard";
import { ScheduleView } from "./views/ScheduleView";
import { SkeletonGrid } from "./components/SkeletonGrid";
import { EmptyState } from "./components/EmptyState";

const embedded = isEmbedded();

function renderView(payload: ViewPayload) {
  switch (payload.view) {
    case "search":
      return <SearchGrid payload={payload} />;
    case "list":
      return <ListBrowser payload={payload} />;
    case "detail":
      return <DetailHero payload={payload} />;
    case "ranking":
      return <Rankings payload={payload} />;
    case "seasonal":
      return <SeasonalGrid payload={payload} />;
    case "dashboard":
      return <Dashboard payload={payload} />;
    case "schedule":
      return <ScheduleView payload={payload} />;
    default:
      return <EmptyState message="This tool has no visual view yet." />;
  }
}

const DEV_VIEWS = [
  "search",
  "detail",
  "list",
  "schedule",
  "ranking",
  "seasonal",
  "dashboard",
] as const;

export default function App() {
  const [payload, setPayload] = useState<ViewPayload | null>(
    embedded ? null : devPayload("search"),
  );
  const [stack, setStack] = useState<ViewPayload[]>([]);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hostCtx, setHostCtx] = useState<McpUiHostContext | null>(null);
  const viewSeq = useRef(0);

  useEffect(() => {
    if (!embedded) return;
    start(
      (incoming) => {
        viewSeq.current += 1;
        setStack([]);
        setPending(false);
        setError(null);
        setPayload(incoming);
      },
      (ctx) => {
        applyHostContext(ctx);
        setHostCtx(ctx);
      },
    ).catch((err) => setError(err instanceof Error ? err.message : String(err)));
  }, []);

  const callTool = useCallback(
    async <T,>(name: string, args: Record<string, unknown>): Promise<T> => {
      return embedded ? hostCallTool<T>(name, args) : devCallTool<T>(name, args);
    },
    [],
  );

  const openDetail = useCallback(
    (kind: Kind, id: number) => {
      const tool = kind === "anime" ? "get_anime_detail" : "get_manga_detail";
      const idArg = kind === "anime" ? { anime_id: id } : { manga_id: id };
      setPending(true);
      setError(null);
      callTool<DetailPayload>(tool, idArg)
        .then((detail) => {
          setStack((prev) => (payload ? [...prev, payload] : prev));
          viewSeq.current += 1;
          setPayload({ ...detail, view: "detail", kind });
        })
        .catch((err) => setError(err instanceof Error ? err.message : String(err)))
        .finally(() => setPending(false));
    },
    [callTool, payload],
  );

  const back = useCallback(() => {
    setStack((prev) => {
      const next = [...prev];
      const previous = next.pop();
      if (previous) {
        viewSeq.current += 1;
        setPayload(previous);
      }
      return next;
    });
  }, []);

  const nav = useMemo<Nav>(
    () => ({
      openDetail,
      back,
      canGoBack: stack.length > 0,
      callTool,
      noteToModel: embedded ? noteToModel : (text) => console.info("[model]", text),
      openOnMal: embedded
        ? openOnMal
        : (kind, id) => window.open(`https://myanimelist.net/${kind}/${id}`, "_blank"),
      requestFullscreen: () => void toggleFullscreen(hostCtx),
      hostCtx,
    }),
    [openDetail, back, stack.length, callTool, hostCtx],
  );

  return (
    <NavContext.Provider value={nav}>
      {!embedded && (
        <div className="dev-bar glass" role="toolbar" aria-label="Preview views">
          {DEV_VIEWS.map((view) => (
            <button
              key={view}
              className={`dev-chip${payload && payload.view === view ? " is-active" : ""}`}
              onClick={() => {
                viewSeq.current += 1;
                setStack([]);
                setPayload(devPayload(view));
              }}
            >
              {view}
            </button>
          ))}
        </div>
      )}

      <LayoutGroup>
        <AnimatePresence mode="wait">
          <motion.main
            key={viewSeq.current}
            className="view-root"
            initial={{ opacity: 0, y: 14 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -10 }}
            transition={{ duration: 0.28, ease: [0.22, 1, 0.36, 1] }}
          >
            {payload ? renderView(payload) : <SkeletonGrid label="Waiting for a tool result…" />}
          </motion.main>
        </AnimatePresence>
      </LayoutGroup>

      <AnimatePresence>
        {pending && (
          <motion.div
            className="pending-veil"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            aria-live="polite"
          >
            <div className="pending-spinner" aria-label="Loading" />
          </motion.div>
        )}
        {error && (
          <motion.div
            className="toast toast-error"
            role="alert"
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 16 }}
          >
            {error}
            <button className="toast-dismiss" onClick={() => setError(null)} aria-label="Dismiss">
              ×
            </button>
          </motion.div>
        )}
      </AnimatePresence>
    </NavContext.Provider>
  );
}
