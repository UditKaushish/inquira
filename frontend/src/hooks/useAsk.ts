import { useCallback, useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { askStream } from "@/lib/stream";
import type { Chart, Message, Rating, ResultPayload, Step } from "@/lib/types";

export interface Turn {
  key: string;
  question: string;
  messageId?: string;
  status: "streaming" | "done" | "error";
  live: boolean;
  steps: Step[];
  sql: string | null;
  result: ResultPayload | null;
  chart: Chart | null;
  answer: string | null;
  error: string | null;
  elapsedMs: number | null;
  rating: Rating | null;
}

export function messageToTurn(m: Message): Turn {
  return {
    key: m.id,
    question: m.question,
    messageId: m.id,
    status: m.status === "ok" ? "done" : "error",
    live: false,
    steps: [],
    sql: m.sql,
    result: m.columns.length
      ? { columns: m.columns, rows: m.rows, row_count: m.row_count, truncated: m.truncated, elapsed_ms: m.elapsed_ms }
      : null,
    chart: m.chart,
    answer: m.answer,
    error: m.error,
    elapsedMs: m.elapsed_ms,
    rating: m.rating,
  };
}

function mergeStep(steps: Step[], next: Step): Step[] {
  let idx = -1;
  for (let i = steps.length - 1; i >= 0; i--) if (steps[i].id === next.id) { idx = i; break; }
  if (idx === -1) return [...steps, next];
  // A step that already finished and starts again is a self-repair attempt: append it.
  if (steps[idx].status !== "running" && next.status === "running") return [...steps, { ...next, detail: next.detail ?? "Retrying" }];
  const copy = steps.slice();
  copy[idx] = { ...copy[idx], ...next };
  return copy;
}

/**
 * Owns the list of turns in the current conversation and streams new ones.
 * `onConversation` fires once the server assigns a conversation id.
 */
export function useAsk(onConversation: (id: string) => void) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [conversationId, setConversationId] = useState<string | undefined>();
  const abort = useRef<AbortController | null>(null);
  const qc = useQueryClient();
  const onConvRef = useRef(onConversation);
  onConvRef.current = onConversation;

  useEffect(() => () => abort.current?.abort(), []);

  const patch = (key: string, fn: (t: Turn) => Partial<Turn>) =>
    setTurns((ts) => ts.map((t) => (t.key === key ? { ...t, ...fn(t) } : t)));

  const ask = useCallback(
    async (question: string, convId?: string) => {
      const q = question.trim();
      if (!q) return;
      abort.current?.abort();
      const ctrl = new AbortController();
      abort.current = ctrl;
      const key = `live-${Date.now()}`;
      const started = performance.now();
      setTurns((ts) => [
        ...ts,
        { key, question: q, status: "streaming", live: true, steps: [], sql: null, result: null, chart: null, answer: null, error: null, elapsedMs: null, rating: null },
      ]);

      try {
        let finished = false;
        for await (const ev of askStream({ question: q, conversation_id: convId }, ctrl.signal)) {
          switch (ev.event) {
            case "meta":
              patch(key, () => ({ messageId: ev.data.message_id }));
              if (ev.data.conversation_id !== convId) {
                setConversationId(ev.data.conversation_id);
                onConvRef.current(ev.data.conversation_id);
              }
              break;
            case "step":
              patch(key, (t) => ({ steps: mergeStep(t.steps, ev.data) }));
              break;
            case "sql":
              patch(key, () => ({ sql: ev.data.sql }));
              break;
            case "result":
              patch(key, () => ({ result: ev.data }));
              break;
            case "chart":
              patch(key, () => ({ chart: ev.data }));
              break;
            case "answer":
              patch(key, () => ({ answer: ev.data.text }));
              break;
            case "error":
              finished = true;
              patch(key, (t) => ({
                status: "error",
                error: ev.data.message,
                elapsedMs: performance.now() - started,
                steps: t.steps.map((s) => (s.status === "running" ? { ...s, status: "error" } : s)),
              }));
              break;
            case "done":
              finished = true;
              patch(key, () => ({ status: "done", elapsedMs: ev.data.elapsed_ms, messageId: ev.data.message_id }));
              break;
          }
        }
        if (!finished && !ctrl.signal.aborted) {
          patch(key, () => ({ status: "error", error: "The connection closed before the answer finished.", elapsedMs: performance.now() - started }));
        }
      } catch (e) {
        if (ctrl.signal.aborted) return;
        patch(key, () => ({ status: "error", error: (e as Error).message, elapsedMs: performance.now() - started }));
      } finally {
        qc.invalidateQueries({ queryKey: ["conversations"] });
      }
    },
    [qc],
  );

  const reset = useCallback((next: Turn[] = [], convId?: string) => {
    abort.current?.abort();
    setTurns(next);
    setConversationId(convId);
  }, []);

  const setRating = useCallback((key: string, rating: Rating) => patch(key, () => ({ rating })), []);

  const isStreaming = turns.some((t) => t.status === "streaming");

  return { turns, conversationId, ask, reset, setRating, isStreaming, setConversationId };
}
