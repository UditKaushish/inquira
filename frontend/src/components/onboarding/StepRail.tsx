import { Check } from "lucide-react";
import clsx from "clsx";

export interface RailStep {
  id: string;
  title: string;
  hint: string;
}

export function StepRail({ steps, current, completed }: { steps: RailStep[]; current: number; completed: Set<string> }) {
  return (
    <ol className="space-y-1" aria-label="Setup progress">
      {steps.map((s, i) => {
        const isDone = (completed.has(s.id) || i < current) && i !== current;
        const isCurrent = i === current;
        return (
          <li key={s.id} className="relative flex gap-3 pb-6 last:pb-0" aria-current={isCurrent ? "step" : undefined}>
            {i < steps.length - 1 && (
              <span className={clsx("absolute left-[11px] top-7 h-[calc(100%-28px)] w-px", isDone ? "bg-accent/50" : "bg-border")} aria-hidden />
            )}
            <span
              className={clsx(
                "relative z-10 grid h-6 w-6 shrink-0 place-items-center rounded-full text-[11px] font-semibold transition-colors duration-150",
                isDone && "bg-accent text-accent-fg",
                isCurrent && "bg-surface text-accent ring-2 ring-accent",
                !isDone && !isCurrent && "bg-surface text-muted hairline",
              )}
            >
              {isDone ? <Check className="h-3.5 w-3.5" strokeWidth={3} /> : i + 1}
            </span>
            <div className="pt-0.5">
              <div className={clsx("text-[13px] font-medium", isCurrent ? "text-text" : "text-muted")}>{s.title}</div>
              <div className="text-[12px] text-muted/80">{s.hint}</div>
            </div>
          </li>
        );
      })}
    </ol>
  );
}
