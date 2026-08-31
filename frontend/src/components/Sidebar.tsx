import { useCallback, useEffect, useState } from "react";
import { deleteThread, listThreads, renameThread } from "../net/api";
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
  const [menuFor, setMenuFor] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [renamingFor, setRenamingFor] = useState<string | null>(null);
  const [draftTitle, setDraftTitle] = useState("");
  const activeThread = useStore((s) => s.threadId);
  // Refetch when the run set changes (a new thread materialized on first send).
  const runCount = useStore((s) => s.order.length);

  const refresh = useCallback(() => {
    listThreads().then(setThreads).catch(() => {});
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh, runCount]);

  // Any click outside the open menu closes it; menu/kebab clicks stop
  // propagation so they don't reach this handler. Escape closes too.
  useEffect(() => {
    if (menuFor === null) return;
    const close = () => {
      setMenuFor(null);
      setConfirmDelete(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", onKey);
    };
  }, [menuFor]);

  const grouped: Record<string, ThreadSummary[]> = {};
  for (const t of threads) (grouped[bucketOf(t.updated_at)] ??= []).push(t);

  const select = (id: string) => {
    void loadThread(id);
    onNavigate();
  };

  const toggleMenu = (id: string) => {
    setConfirmDelete(false);
    setMenuFor((cur) => (cur === id ? null : id));
  };

  const startRename = (t: ThreadSummary) => {
    setMenuFor(null);
    setConfirmDelete(false);
    setDraftTitle(t.title);
    setRenamingFor(t.thread_id);
  };

  const commitRename = async (id: string) => {
    const title = draftTitle.trim();
    setRenamingFor(null);
    if (!title) return;
    await renameThread(id, title);
    refresh();
  };

  const doDelete = async (id: string) => {
    setMenuFor(null);
    setConfirmDelete(false);
    await deleteThread(id);
    if (id === activeThread) newChat();
    refresh();
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
                  <div
                    key={t.thread_id}
                    className={`da-thread-row ${t.thread_id === activeThread ? "is-active" : ""} ${
                      menuFor === t.thread_id ? "menu-open" : ""
                    }`}
                  >
                    {renamingFor === t.thread_id ? (
                      <input
                        className="da-rename-input"
                        value={draftTitle}
                        autoFocus
                        onChange={(e) => setDraftTitle(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") void commitRename(t.thread_id);
                          if (e.key === "Escape") setRenamingFor(null);
                        }}
                        onBlur={() => setRenamingFor(null)}
                      />
                    ) : (
                      <>
                        <button className="da-thread" onClick={() => select(t.thread_id)} title={t.title}>
                          {t.title}
                        </button>
                        <button
                          className="da-kebab"
                          aria-label={`Options for ${t.title}`}
                          aria-haspopup="menu"
                          aria-expanded={menuFor === t.thread_id}
                          onMouseDown={(e) => e.stopPropagation()}
                          onClick={() => toggleMenu(t.thread_id)}
                        >
                          ⋯
                        </button>
                        {menuFor === t.thread_id && (
                          <div className="da-thread-menu" role="menu" onMouseDown={(e) => e.stopPropagation()}>
                            {!confirmDelete ? (
                              <>
                                <button role="menuitem" onClick={() => startRename(t)}>
                                  Rename
                                </button>
                                <button role="menuitem" className="is-danger" onClick={() => setConfirmDelete(true)}>
                                  Delete
                                </button>
                              </>
                            ) : (
                              <>
                                <div className="da-menu-label">Delete this chat?</div>
                                <button role="menuitem" className="is-danger" onClick={() => void doDelete(t.thread_id)}>
                                  Confirm delete
                                </button>
                                <button
                                  role="menuitem"
                                  onClick={() => {
                                    setMenuFor(null);
                                    setConfirmDelete(false);
                                  }}
                                >
                                  Cancel
                                </button>
                              </>
                            )}
                          </div>
                        )}
                      </>
                    )}
                  </div>
                ))}
            </div>
          );
        })}
      </div>
    </aside>
  );
}
