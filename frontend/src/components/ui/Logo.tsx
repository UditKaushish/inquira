import clsx from "clsx";

export function LogoMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={clsx("shrink-0", className ?? "h-7 w-7")} aria-hidden>
      <rect width="32" height="32" rx="8" className="fill-accent" />
      <circle cx="16" cy="9.5" r="2.5" className="fill-accent-fg" />
      <path d="M13 14h4.5v9.5H20" fill="none" className="stroke-accent-fg" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function Logo({ className }: { className?: string }) {
  return (
    <span className={clsx("inline-flex items-center gap-2", className)}>
      <LogoMark />
      <span className="text-[15px] font-semibold tracking-tight">Inquira</span>
    </span>
  );
}
