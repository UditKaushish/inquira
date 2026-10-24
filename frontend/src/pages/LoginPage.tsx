import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation } from "@tanstack/react-query";
import { api, ApiError } from "@/lib/api";
import { useSessionActions } from "@/hooks/useSession";
import { LogoMark } from "@/components/ui/Logo";
import { Button } from "@/components/ui/Button";
import { Field, Input } from "@/components/ui/Input";
import { Callout } from "@/components/ui/Callout";

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const { setUser, refreshSetup } = useSessionActions();
  const navigate = useNavigate();

  const login = useMutation({
    mutationFn: () => api.login({ email: email.trim(), password }),
    onSuccess: async (r) => {
      setUser(r.user);
      await refreshSetup();
      navigate("/app", { replace: true });
    },
  });

  return (
    <div className="grid min-h-full place-items-center bg-bg px-4 py-12">
      <div className="w-full max-w-[360px]">
        <div className="mb-8 flex flex-col items-center text-center">
          <LogoMark className="h-10 w-10" />
          <h1 className="mt-5 text-xl font-semibold tracking-tight">Sign in to Inquira</h1>
          <p className="mt-1 text-sm text-muted">Ask your data anything.</p>
        </div>
        <form
          className="space-y-4 rounded-xl bg-surface p-6 hairline"
          onSubmit={(e) => {
            e.preventDefault();
            login.mutate();
          }}
        >
          <Field label="Email" htmlFor="login-email">
            <Input id="login-email" type="email" autoComplete="email" autoFocus required value={email} onChange={(e) => setEmail(e.target.value)} />
          </Field>
          <Field label="Password" htmlFor="login-password">
            <Input id="login-password" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
          </Field>
          {login.isError && <Callout tone="danger">{login.error instanceof ApiError && login.error.status === 401 ? "That email and password don't match." : login.error.message}</Callout>}
          <Button type="submit" className="w-full" loading={login.isPending}>
            Sign in
          </Button>
        </form>
        <p className="mt-6 text-center text-[12px] text-muted">No account? Ask your workspace admin for an invite.</p>
      </div>
    </div>
  );
}
