import { useMemo } from "react";
import { NavLink, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Database, BookOpen, Users, Settings, ScrollText, Plus, Trash2, MessageSquare } from "lucide-react";
import clsx from "clsx";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { relativeGroup } from "@/lib/format";
import type { ConversationSummary } from "@/lib/types";
import { useMe } from "@/hooks/useSession";
import { Logo } from "../ui/Logo";
import { Button } from "../ui/Button";
import { useConfirm } from "../ui/Dialog";
import { UserMenu } from "./UserMenu";

const adminNav = [
  { to: "/app/data", label: "Data", icon: Database, adminOnly: false },
  { to: "/app/knowledge", label: "Knowledge", icon: BookOpen, adminOnly: false },
  { to: "/app/members", label: "Members", icon: Users, adminOnly: true },
  { to: "/app/settings", label: "Settings", icon: Settings, adminOnly: true },
  { to: "/app/audit", label: "Audit log", icon: ScrollText, adminOnly: true },
];

const GROUPS = ["Today", "Previous 7 days", "Older"] as const;

export function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const me = useMe();
  const isAdmin = me.data?.role === "admin";
  const navigate = useNavigate();
  const { conversationId } = useParams();
  const qc = useQueryClient();
  const confirm = useConfirm();

  const conversations = useQuery({ queryKey: ["conversations"], queryFn: api.conversations });

  const remove = useMutation({
    mutationFn: (id: string) => api.deleteConversation(id),
    onSuccess: (_, id) => {
      qc.invalidateQueries({ queryKey: ["conversations"] });
      if (id === conversationId) navigate("/app");
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const grouped = useMemo(() => {
    const out: Record<(typeof GROUPS)[number], ConversationSummary[]> = { Today: [], "Previous 7 days": [], Older: [] };
    for (const c of conversations.data?.conversations ?? []) out[relativeGroup(c.updated_at)].push(c);
    return out;
  }, [conversations.data]);

  const onDelete = async (c: ConversationSummary) => {
    const ok = await confirm({
      title: "Delete conversation?",
      description: `"${c.title}" and its results will be permanently removed.`,
      confirmLabel: "Delete",
      danger: true,
    });
    if (ok) remove.mutate(c.id);
  };

  const navClass = ({ isActive }: { isActive: boolean }) =>
    clsx(
      "flex h-8 items-center gap-2.5 rounded-md px-2.5 text-[13px] transition-colors duration-150",
      isActive ? "bg-surface-2 font-medium text-text" : "text-muted hover:bg-surface-2 hover:text-text",
    );

  return (
    <div className="flex h-full flex-col">
      <div className="flex h-14 items-center px-4">
        <Logo />
      </div>

      <div className="px-3">
        <Button
          variant="secondary"
          className="w-full justify-start"
          onClick={() => {
            navigate("/app", { state: { fresh: Date.now() } });
            onNavigate?.();
          }}
        >
          <Plus className="h-4 w-4" aria-hidden />
          New question
          <kbd className="ml-auto rounded border border-border px-1 font-sans text-[10px] text-muted">⌘K</kbd>
        </Button>
      </div>

      <nav aria-label="Conversation history" className="mt-4 min-h-0 flex-1 overflow-y-auto px-3 pb-3">
        {conversations.isPending && (
          <div className="space-y-2 px-1">
            {[0, 1, 2].map((i) => (
              <div key={i} className="h-6 animate-pulse rounded bg-surface-2" />
            ))}
          </div>
        )}
        {conversations.data && conversations.data.conversations.length === 0 && (
          <p className="px-2.5 py-2 text-[13px] text-muted">Your questions will appear here.</p>
        )}
        {GROUPS.map((g) =>
          grouped[g].length ? (
            <div key={g} className="mb-4">
              <h4 className="px-2.5 pb-1 text-[11px] font-medium uppercase tracking-wide text-muted/80">{g}</h4>
              <ul className="space-y-px">
                {grouped[g].map((c) => (
                  <li key={c.id} className="group relative">
                    <NavLink to={`/app/c/${c.id}`} onClick={onNavigate} className={(s) => clsx(navClass(s), "pr-8")}>
                      <MessageSquare className="h-3.5 w-3.5 shrink-0 opacity-60" aria-hidden />
                      <span className="truncate">{c.title}</span>
                    </NavLink>
                    <button
                      type="button"
                      onClick={() => onDelete(c)}
                      aria-label={`Delete ${c.title}`}
                      className="absolute right-1 top-1/2 hidden h-6 w-6 -translate-y-1/2 place-items-center rounded text-muted hover:bg-surface hover:text-danger focus-visible:grid group-hover:grid"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          ) : null,
        )}
      </nav>

      <div className="border-t border-border p-3">
        <ul className="mb-2 space-y-px">
          {adminNav
            .filter((n) => isAdmin || !n.adminOnly)
            .map((n) => (
              <li key={n.to}>
                <NavLink to={n.to} onClick={onNavigate} className={navClass}>
                  <n.icon className="h-4 w-4" aria-hidden />
                  {n.label}
                </NavLink>
              </li>
            ))}
        </ul>
        <UserMenu />
      </div>
    </div>
  );
}
