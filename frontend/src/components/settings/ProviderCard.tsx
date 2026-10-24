import type { ReactNode } from "react";
import { Check } from "lucide-react";
import clsx from "clsx";

export function ProviderCard({
  selected,
  onSelect,
  title,
  description,
  badge,
  icon,
}: {
  selected: boolean;
  onSelect: () => void;
  title: string;
  description: string;
  badge?: ReactNode;
  icon?: ReactNode;
}) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={selected}
      onClick={onSelect}
      className={clsx(
        "group relative flex w-full items-start gap-3 rounded-xl bg-surface p-3.5 text-left transition-all duration-150",
        selected ? "border border-accent ring-4 ring-accent/10" : "hairline hover:border-text/20",
      )}
    >
      {icon && <span className="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-surface-2 text-muted">{icon}</span>}
      <span className="min-w-0 flex-1">
        <span className="flex flex-wrap items-center gap-2 text-sm font-medium text-text">
          {title}
          {badge}
        </span>
        <span className="mt-0.5 block text-[13px] leading-snug text-muted">{description}</span>
      </span>
      <span
        className={clsx(
          "mt-0.5 grid h-4 w-4 shrink-0 place-items-center rounded-full transition-colors",
          selected ? "bg-accent text-accent-fg" : "border border-border",
        )}
        aria-hidden
      >
        {selected && <Check className="h-2.5 w-2.5" strokeWidth={3} />}
      </span>
    </button>
  );
}
