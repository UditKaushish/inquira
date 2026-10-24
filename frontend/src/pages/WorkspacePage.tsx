import { useEffect, useRef } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Sparkles } from "lucide-react";
import { api } from "@/lib/api";
import { messageToTurn, useAsk } from "@/hooks/useAsk";
import { useMe, useSetupStatus } from "@/hooks/useSession";
import { Composer, type ComposerHandle } from "@/components/ask/Composer";
import { AnswerCard } from "@/components/ask/AnswerCard";
import { Spinner } from "@/components/ui/Spinner";
import { Callout } from "@/components/ui/Callout";

function greeting(name?: string) {
  const h = new Date().getHours();
  const part = h < 5 ? "Working late" : h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
  const first = name?.split(" ")[0];
  return first ? `${part}, ${first}` : part;
}

export default function WorkspacePage() {
  const { conversationId } = useParams();
  const location = useLocation();
  const navigate = useNavigate();
  const me = useMe();
  const setup = useSetupStatus();
  const composer = useRef<ComposerHandle>(null);
  const bottom = useRef<HTMLDivElement>(null);
  const liveConv = useRef<string | undefined>(undefined);

  const { turns, ask, reset, setRating, isStreaming, conversationId: activeConv } = useAsk((id) => {
    liveConv.current = id;
    navigate(`/app/c/${id}`, { replace: true });
  });

  // Load a stored conversation unless it's the one we're streaming into.
  const stored = useQuery({
    queryKey: ["conversation", conversationId],
    queryFn: () => api.conversation(conversationId!),
    enabled: !!conversationId && conversationId !== liveConv.current,
  });

  useEffect(() => {
    if (conversationId && conversationId === liveConv.current) return;
    liveConv.current = conversationId;
    reset([], conversationId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conversationId, location.key]);

  useEffect(() => {
    if (stored.data && stored.data.id === conversationId && turns.length === 0) {
      reset(stored.data.messages.map(messageToTurn), stored.data.id);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stored.data]);

  // A question handed over from onboarding.
  useEffect(() => {
    const q = (location.state as { ask?: string } | null)?.ask;
    if (q) {
      navigate(location.pathname, { replace: true, state: null });
      ask(q);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [turns.length]);

  const suggestions = useQuery({ queryKey: ["suggestions"], queryFn: api.suggestions, staleTime: 5 * 60_000, enabled: turns.length === 0 && !conversationId });

  const submit = (q: string) => ask(q, activeConv ?? conversationId);
  const notReady = setup.data && !setup.data.completed;

  if (conversationId && stored.isPending && turns.length === 0) {
    return (
      <div className="grid h-full place-items-center">
        <Spinner className="h-5 w-5 text-muted" />
      </div>
    );
  }

  if (turns.length === 0) {
    return (
      <div className="mx-auto flex min-h-full w-full max-w-2xl flex-col justify-center px-4 py-12 sm:px-6">
        <h1 className="text-2xl font-semibold tracking-tight sm:text-[28px]">{greeting(me.data?.name)}</h1>
        <p className="mt-1.5 text-[15px] text-muted">What would you like to know about your data?</p>
        {notReady && (
          <Callout className="mt-6">An admin still needs to finish connecting a data source and an AI model before questions can be answered.</Callout>
        )}
        {stored.isError && <Callout tone="danger" className="mt-6">{stored.error.message}</Callout>}
        <div className="mt-6">
          <Composer ref={composer} onSubmit={submit} large disabled={!!notReady} />
        </div>
        <div className="mt-5">
          {suggestions.isPending ? (
            <div className="flex flex-wrap gap-2">
              {[140, 180, 120].map((w) => (
                <div key={w} className="h-8 animate-pulse rounded-full bg-surface-2" style={{ width: w }} />
              ))}
            </div>
          ) : (
            <ul className="flex flex-wrap gap-2" aria-label="Suggested questions">
              {(suggestions.data?.questions ?? []).slice(0, 6).map((q) => (
                <li key={q}>
                  <button
                    type="button"
                    disabled={!!notReady}
                    onClick={() => submit(q)}
                    className="inline-flex items-center gap-1.5 rounded-full bg-surface px-3 py-1.5 text-left text-[13px] text-muted hairline transition-colors duration-150 hover:border-accent/40 hover:text-text disabled:opacity-50"
                  >
                    <Sparkles className="h-3.5 w-3.5 shrink-0 text-accent" aria-hidden />
                    {q}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-full flex-col">
      <div className="mx-auto w-full max-w-3xl flex-1 space-y-10 px-4 pb-8 pt-8 sm:px-6">
        {turns.map((t) => (
          <section key={t.key} className="space-y-5">
            <div className="flex justify-end">
              <p className="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-br-md bg-surface-2 px-4 py-2.5 text-[14.5px] leading-relaxed">{t.question}</p>
            </div>
            <AnswerCard turn={t} onRetry={submit} onRated={setRating} />
          </section>
        ))}
        <div ref={bottom} />
      </div>
      <div className="sticky bottom-0 bg-gradient-to-t from-bg via-bg to-bg/0 pb-4 pt-6">
        <div className="mx-auto w-full max-w-3xl px-4 sm:px-6">
          <Composer ref={composer} onSubmit={submit} busy={isStreaming} onStop={() => reset(turns.map((t) => (t.status === "streaming" ? { ...t, status: "error", error: "Stopped." } : t)), activeConv)} placeholder="Ask a follow-up…" />
          <p className="mt-2 text-center text-[11px] text-muted/80">Inquira runs read-only queries. Check the SQL tab to see exactly what ran.</p>
        </div>
      </div>
    </div>
  );
}
