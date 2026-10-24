import { useEffect, useState } from "react";
import { Outlet, useLocation } from "react-router-dom";
import { Menu } from "lucide-react";
import clsx from "clsx";
import { Sidebar } from "./Sidebar";
import { Logo } from "../ui/Logo";
import { Button } from "../ui/Button";

export function AppShell() {
  const [drawer, setDrawer] = useState(false);
  const location = useLocation();

  useEffect(() => setDrawer(false), [location.pathname]);

  useEffect(() => {
    if (!drawer) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setDrawer(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [drawer]);

  return (
    <div className="flex h-full">
      {/* Desktop sidebar */}
      <aside className="hidden w-[260px] shrink-0 border-r border-border bg-surface md:block">
        <Sidebar />
      </aside>

      {/* Mobile drawer */}
      <div className={clsx("fixed inset-0 z-40 md:hidden", drawer ? "" : "pointer-events-none")} aria-hidden={!drawer}>
        <div
          className={clsx("absolute inset-0 bg-black/40 transition-opacity duration-150", drawer ? "opacity-100" : "opacity-0")}
          onClick={() => setDrawer(false)}
        />
        <aside
          className={clsx(
            "absolute inset-y-0 left-0 w-[280px] max-w-[85vw] border-r border-border bg-surface transition-transform duration-150",
            drawer ? "translate-x-0" : "-translate-x-full",
          )}
        >
          {drawer && <Sidebar onNavigate={() => setDrawer(false)} />}
        </aside>
      </div>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-12 items-center gap-2 border-b border-border bg-surface px-3 md:hidden">
          <Button variant="ghost" size="icon" aria-label="Open menu" onClick={() => setDrawer(true)}>
            <Menu className="h-4 w-4" />
          </Button>
          <Logo />
        </header>
        <main className="min-h-0 flex-1 overflow-y-auto">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
