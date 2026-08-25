import { useCallback, useEffect, useState } from "react";
import { listThreads } from "../net/api";
import { newChat, loadThread } from "../net/controller";
import { useStore } from "../store/store";
import type { ThreadSummary } from "../store/types";
import "./Sidebar.css";

type Props = { open: boolean; onNavigate: () => void };

const ORDER = ["Today", "Yesterday", "Previous 7 days", "Older"] as const;

function bucketOf(iso: string): string {
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "Older";
  const now = new Date();
  const startToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const startThat = new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const days = Math.floor((startToday - startThat) / 86400000);
  if (days <= 0) return "Today";
  if (days === 1) return "Yesterday";
  if (days <= 7) return "Previous 7 days";
  return "Older";
}

export function Sidebar({ open, onNavigate }: Props) {
  const [threads, setThreads] = useState<ThreadSummary[]>([]);
  const [olderOpen, setOlderOpen] = useState(false);
  const activeThread = useStore((s) => s.threadId);
  // Refetch when the run set changes (a new thread materialized on first send).
  const runCount = useStore((s) => s.order.length);

  const refresh = useCallback(() => {
    listThreads().then(setThreads).catch(() => {});
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh, runCount]);

  const grouped: Record<string, ThreadSummary[]> = {};
  for (const t of threads) (grouped[bucketOf(t.updated_at)] ??= []).push(t);

  const select = (id: string) => {
    void loadThread(id);
    onNavigate();
  };

  return (
    <aside className={`da-sidebar ${open ? "is-open" : "is-closed"}`}>
      <button
        className="da-newchat"
        onClick={() => {
          newChat();
          refresh();
          onNavigate();
        }}
      >
        + New chat
      </button>

      <div className="da-thread-list">
        {threads.length === 0 && <p className="da-thread-empty">No conversations yet.</p>}
        {ORDER.map((section) => {
          const items = grouped[section];
          if (!items || items.length === 0) return null;
          const collapsible = section === "Older";
          const collapsed = collapsible && !olderOpen;
          return (
            <div key={section} className="da-thread-section">
              <div
                className={`da-section-head ${collapsible ? "is-collapsible" : ""}`}
                onClick={collapsible ? () => setOlderOpen((o) => !o) : undefined}
              >
                {section}
                {collapsible && <span className="da-section-count">{collapsed ? `▸ ${items.length}` : "▾"}</span>}
              </div>
              {!collapsed &&
                items.map((t) => (
                  <button
                    key={t.thread_id}
                    className={`da-thread ${t.thread_id === activeThread ? "is-active" : ""}`}
                    onClick={() => select(t.thread_id)}
                    title={t.title}
                  >
                    {t.title}
                  </button>
                ))}
            </div>
          );
        })}
      </div>
    </aside>
  );
}
