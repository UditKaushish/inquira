import { useEffect, useState } from "react";
import { Check, ChevronDown, X } from "lucide-react";
import clsx from "clsx";
import type { Step } from "@/lib/types";
import { formatDuration } from "@/lib/format";
import { Spinner } from "../ui/Spinner";

export function StepTimeline({ steps, done, elapsedMs }: { steps: Step[]; done: boolean; elapsedMs: number | null }) {
  const [open, setOpen] = useState(!done);
  useEffect(() => setOpen(!done), [done]);

  if (!steps.length) {
    return (
      <div className="flex items-center gap-2 text-[13px] text-muted">
        <Spinner className="h-3.5 w-3.5" /> Starting…
      </div>
    );
  }

  const failed = steps.some((s) => s.status === "error");
  const summary = failed
    ? `Stopped after ${steps.length} steps`
    : `Answered in ${elapsedMs != null ? formatDuration(elapsedMs) : "—"} · ${steps.length} steps`;

  return (
    <div>
      {done && (
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          className="flex items-center gap-1.5 text-[12px] text-muted transition-colors hover:text-text"
        >
          {failed ? <X className="h-3.5 w-3.5 text-danger" /> : <Check className="h-3.5 w-3.5 text-success" />}
          {summary}
          <ChevronDown className={clsx("h-3.5 w-3.5 transition-transform duration-150", open && "rotate-180")} />
        </button>
      )}
      {open && (
        <ol className={clsx("relative space-y-2", done && "mt-3")} aria-live="polite">
          {steps.map((s, i) => (
            <li key={`${s.id}-${i}`} className="relative flex items-start gap-2.5 animate-fade-in">
              {i < steps.length - 1 && <span className="absolute left-[7px] top-5 h-[calc(100%-4px)] w-px bg-border" aria-hidden />}
              <span className="relative z-10 mt-0.5 grid h-[15px] w-[15px] shrink-0 place-items-center rounded-full bg-surface">
                {s.status === "running" ? (
                  <Spinner className="h-3.5 w-3.5 text-accent" label={s.label} />
                ) : s.status === "done" ? (
                  <span className="grid h-[15px] w-[15px] place-items-center rounded-full bg-success/15 text-success">
                    <Check className="h-2.5 w-2.5" strokeWidth={3} />
                  </span>
                ) : (
                  <span className="grid h-[15px] w-[15px] place-items-center rounded-full bg-danger/15 text-danger">
                    <X className="h-2.5 w-2.5" strokeWidth={3} />
                  </span>
                )}
              </span>
              <div className="min-w-0 text-[13px] leading-5">
                <span className={clsx(s.status === "running" ? "text-text" : "text-muted")}>{s.label}</span>
                {s.detail && <span className="ml-2 text-muted/80">{s.detail}</span>}
              </div>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
