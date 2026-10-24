import type { ReactNode } from "react";
import clsx from "clsx";
import { AlertCircle, CheckCircle2, Info } from "lucide-react";

type Tone = "info" | "success" | "danger";
const styles: Record<Tone, string> = {
  info: "bg-surface-2 text-text",
  success: "bg-success/10 text-success",
  danger: "bg-danger/10 text-danger",
};
const icons = { info: Info, success: CheckCircle2, danger: AlertCircle };

export function Callout({ tone = "info", children, action, className }: { tone?: Tone; children: ReactNode; action?: ReactNode; className?: string }) {
  const Icon = icons[tone];
  return (
    <div role={tone === "danger" ? "alert" : "status"} className={clsx("flex items-start gap-2.5 rounded-lg px-3 py-2.5 text-[13px]", styles[tone], className)}>
      <Icon className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
      <div className="min-w-0 flex-1 break-words leading-relaxed">{children}</div>
      {action}
    </div>
  );
}
