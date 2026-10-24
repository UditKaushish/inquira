import { useEffect, useState } from "react";
import { BarChart3, Code2, RotateCcw, Table2, ThumbsDown, ThumbsUp } from "lucide-react";
import clsx from "clsx";
import { toast } from "sonner";
import type { Turn } from "@/hooks/useAsk";
import type { Rating } from "@/lib/types";
import { api } from "@/lib/api";
import { formatDuration, formatNumber } from "@/lib/format";
import { Tabs } from "../ui/Tabs";
import { Callout } from "../ui/Callout";
import { Button } from "../ui/Button";
import { LogoMark } from "../ui/Logo";
import { StepTimeline } from "./StepTimeline";
import { Markdown } from "./Markdown";
import { ResultTable } from "./ResultTable";
import { ResultChart, isChartable } from "./ResultChart";
import { SqlView } from "./SqlView";

type View = "chart" | "table" | "sql";

export function AnswerCard({ turn, onRetry, onRated }: { turn: Turn; onRetry: (q: string) => void; onRated: (key: string, r: Rating) => void }) {
  const { result, chart, sql } = turn;
  const chartable = !!result && isChartable(chart, result);
  const preferred: View = chartable ? "chart" : result ? "table" : "sql";
  const [view, setView] = useState<View>(preferred);
  const [touched, setTouched] = useState(false);

  useEffect(() => {
    if (!touched) setView(preferred);
  }, [preferred, touched]);

  const rate = async (r: Rating) => {
    if (!turn.messageId) return;
    onRated(turn.key, r);
    try {
      await api.feedback(turn.messageId, r);
      toast.success(r === 1 ? "Thanks, glad it helped." : "Thanks, we'll use this to improve.");
    } catch (e) {
      toast.error((e as Error).message);
    }
  };

  const showBody = !!(result || sql || turn.answer);

  return (
    <article className="flex gap-3 animate-fade-in" aria-busy={turn.status === "streaming"}>
      <LogoMark className="mt-0.5 h-6 w-6" />
      <div className="min-w-0 flex-1 space-y-4">
        {turn.live && <StepTimeline steps={turn.steps} done={turn.status !== "streaming"} elapsedMs={turn.elapsedMs} />}

        {turn.answer && <Markdown text={turn.answer} />}

        {turn.status === "error" && (
          <Callout
            tone="danger"
            action={
              <Button variant="ghost" size="sm" className="-my-1 text-danger hover:text-danger" onClick={() => onRetry(turn.question)}>
                <RotateCcw className="h-3.5 w-3.5" /> Retry
              </Button>
            }
          >
            {turn.error ?? "Something went wrong."}
          </Callout>
        )}

        {showBody && (result || sql) && (
          <div className="rounded-xl bg-surface p-3 hairline sm:p-4">
            <div className="mb-3 flex items-center justify-between gap-2">
              <Tabs<View>
                value={view}
                onChange={(v) => {
                  setTouched(true);
                  setView(v);
                }}
                items={[
                  { id: "chart", label: <><BarChart3 className="h-3.5 w-3.5" /> Chart</>, disabled: !chartable },
                  { id: "table", label: <><Table2 className="h-3.5 w-3.5" /> Table</>, disabled: !result },
                  { id: "sql", label: <><Code2 className="h-3.5 w-3.5" /> SQL</>, disabled: !sql },
                ]}
              />
            </div>
            {view === "chart" && result && chartable && <ResultChart chart={chart} result={result} />}
            {view === "table" && result && <ResultTable result={result} />}
            {view === "sql" && sql && <SqlView sql={sql} />}
          </div>
        )}

        {turn.status === "done" && (
          <footer className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px] text-muted">
            {result && <span className="tabular-nums">{formatNumber(result.row_count)} rows</span>}
            {turn.elapsedMs != null && <span className="tabular-nums">{formatDuration(turn.elapsedMs)}</span>}
            {turn.messageId && (
              <span className="ml-auto flex items-center gap-0.5">
                <FeedbackButton active={turn.rating === 1} label="Helpful" onClick={() => rate(1)}>
                  <ThumbsUp className="h-3.5 w-3.5" />
                </FeedbackButton>
                <FeedbackButton active={turn.rating === -1} label="Not helpful" onClick={() => rate(-1)}>
                  <ThumbsDown className="h-3.5 w-3.5" />
                </FeedbackButton>
              </span>
            )}
          </footer>
        )}
      </div>
    </article>
  );
}

function FeedbackButton({ active, label, onClick, children }: { active: boolean; label: string; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      aria-label={label}
      aria-pressed={active}
      onClick={onClick}
      className={clsx("grid h-7 w-7 place-items-center rounded-md transition-colors duration-150 hover:bg-surface-2", active ? "text-accent" : "text-muted hover:text-text")}
    >
      {children}
    </button>
  );
}
