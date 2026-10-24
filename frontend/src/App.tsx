import type { ReactNode } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { useMe, useSetupStatus } from "./hooks/useSession";
import { Spinner } from "./components/ui/Spinner";
import { Callout } from "./components/ui/Callout";
import { Button } from "./components/ui/Button";
import { AppShell } from "./components/layout/AppShell";
import SetupPage from "./pages/SetupPage";
import LoginPage from "./pages/LoginPage";
import WorkspacePage from "./pages/WorkspacePage";
import DataPage from "./pages/DataPage";
import KnowledgePage from "./pages/KnowledgePage";
import MembersPage from "./pages/MembersPage";
import SettingsPage from "./pages/SettingsPage";
import AuditPage from "./pages/AuditPage";

function FullScreen({ children }: { children: ReactNode }) {
  return <div className="grid min-h-full place-items-center p-6">{children}</div>;
}

/** Decides where a visitor belongs based on setup status and session. */
function Gate({ children, area }: { children: ReactNode; area: "setup" | "login" | "app" }) {
  const status = useSetupStatus();
  const me = useMe();
  const location = useLocation();

  if (status.isPending || me.isPending) {
    return (
      <FullScreen>
        <Spinner className="h-5 w-5 text-muted" />
      </FullScreen>
    );
  }
  if (status.isError || me.isError) {
    return (
      <FullScreen>
        <div className="w-full max-w-md space-y-3">
          <Callout tone="danger">{(status.error ?? me.error)?.message ?? "Something went wrong."}</Callout>
          <Button variant="secondary" onClick={() => window.location.reload()}>
            Try again
          </Button>
        </div>
      </FullScreen>
    );
  }

  const s = status.data;
  const user = me.data;
  let allowed: boolean;
  let fallback: string;
  if (s.needs_admin) {
    allowed = area === "setup";
    fallback = "/setup";
  } else if (!user) {
    allowed = area === "login";
    fallback = "/login";
  } else if (user.role === "admin") {
    // Admins may revisit setup; they're sent there until it's complete.
    allowed = area === "setup" || (area === "app" && s.completed);
    fallback = s.completed ? "/app" : "/setup";
  } else {
    // Members always land in the app (it shows a notice if setup is incomplete).
    allowed = area === "app";
    fallback = "/app";
  }

  if (!allowed) return <Navigate to={fallback} replace state={{ from: location.pathname }} />;
  return <>{children}</>;
}

export default function App() {
  return (
    <Routes>
      <Route path="/setup" element={<Gate area="setup"><SetupPage /></Gate>} />
      <Route path="/login" element={<Gate area="login"><LoginPage /></Gate>} />
      <Route path="/app" element={<Gate area="app"><AppShell /></Gate>}>
        <Route index element={<WorkspacePage />} />
        <Route path="c/:conversationId" element={<WorkspacePage />} />
        <Route path="data" element={<DataPage />} />
        <Route path="knowledge" element={<KnowledgePage />} />
        <Route path="members" element={<MembersPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="audit" element={<AuditPage />} />
        <Route path="*" element={<Navigate to="/app" replace />} />
      </Route>
      <Route path="*" element={<Navigate to="/app" replace />} />
    </Routes>
  );
}
