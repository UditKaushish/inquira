import { useId, type ReactNode } from "react";
import clsx from "clsx";

export interface TabItem<T extends string> {
  id: T;
  label: ReactNode;
  disabled?: boolean;
}

export function Tabs<T extends string>({
  items,
  value,
  onChange,
  className,
}: {
  items: TabItem<T>[];
  value: T;
  onChange: (v: T) => void;
  className?: string;
}) {
  const base = useId();
  const onKey = (e: React.KeyboardEvent, i: number) => {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    e.preventDefault();
    const enabled = items.filter((t) => !t.disabled);
    const cur = enabled.findIndex((t) => t.id === items[i].id);
    const next = enabled[(cur + (e.key === "ArrowRight" ? 1 : enabled.length - 1)) % enabled.length];
    onChange(next.id);
    document.getElementById(`${base}-${next.id}`)?.focus();
  };
  return (
    <div role="tablist" className={clsx("inline-flex items-center gap-0.5 rounded-lg bg-surface-2 p-0.5", className)}>
      {items.map((t, i) => (
        <button
          key={t.id}
          id={`${base}-${t.id}`}
          role="tab"
          type="button"
          aria-selected={value === t.id}
          tabIndex={value === t.id ? 0 : -1}
          disabled={t.disabled}
          onKeyDown={(e) => onKey(e, i)}
          onClick={() => onChange(t.id)}
          className={clsx(
            "inline-flex h-7 items-center gap-1.5 rounded-md px-2.5 text-[13px] font-medium transition-colors duration-150 disabled:opacity-40",
            value === t.id ? "bg-surface text-text shadow-sm" : "text-muted hover:text-text",
          )}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}
