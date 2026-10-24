import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ChevronsUpDown, LogOut, Monitor, Moon, Sun } from "lucide-react";
import clsx from "clsx";
import { useMe, useSessionActions } from "@/hooks/useSession";
import { useTheme, type ThemePref } from "@/lib/theme";

const themes: { id: ThemePref; label: string; icon: typeof Sun }[] = [
  { id: "system", label: "System", icon: Monitor },
  { id: "light", label: "Light", icon: Sun },
  { id: "dark", label: "Dark", icon: Moon },
];

export function UserMenu() {
  const me = useMe();
  const { signOut } = useSessionActions();
  const { pref, setTheme } = useTheme();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => !ref.current?.contains(e.target as Node) && setOpen(false);
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const user = me.data;
  if (!user) return null;
  const initials = (user.name || user.email).split(/[\s@.]+/).filter(Boolean).slice(0, 2).map((s) => s[0]!.toUpperCase()).join("");

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2.5 rounded-lg p-1.5 text-left transition-colors duration-150 hover:bg-surface-2"
      >
        <span className="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-accent/12 text-[11px] font-semibold text-accent">{initials}</span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[13px] font-medium">{user.name || user.email}</span>
          <span className="block truncate text-[11px] capitalize text-muted">{user.role}</span>
        </span>
        <ChevronsUpDown className="h-3.5 w-3.5 text-muted" aria-hidden />
      </button>

      {open && (
        <div role="menu" className="absolute bottom-full left-0 right-0 mb-2 rounded-xl bg-surface p-1.5 shadow-popover hairline animate-fade-in">
          <div className="truncate px-2 py-1.5 text-xs text-muted">{user.email}</div>
          <div className="px-2 pb-1 pt-2 text-[11px] font-medium uppercase tracking-wide text-muted/80">Theme</div>
          <div className="mx-1 mb-1 grid grid-cols-3 gap-1 rounded-lg bg-surface-2 p-0.5" role="radiogroup" aria-label="Theme">
            {themes.map((t) => (
              <button
                key={t.id}
                type="button"
                role="radio"
                aria-checked={pref === t.id}
                onClick={() => setTheme(t.id)}
                className={clsx(
                  "flex h-7 items-center justify-center gap-1 rounded-md text-[12px] transition-colors duration-150",
                  pref === t.id ? "bg-surface text-text shadow-sm" : "text-muted hover:text-text",
                )}
              >
                <t.icon className="h-3.5 w-3.5" aria-hidden />
                {t.label}
              </button>
            ))}
          </div>
          <div className="my-1 h-px bg-border" />
          <button
            type="button"
            role="menuitem"
            onClick={async () => {
              await signOut();
              navigate("/login", { replace: true });
            }}
            className="flex h-8 w-full items-center gap-2 rounded-md px-2 text-[13px] text-text hover:bg-surface-2"
          >
            <LogOut className="h-4 w-4 text-muted" aria-hidden />
            Sign out
          </button>
        </div>
      )}
    </div>
  );
}
