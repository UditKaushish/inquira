import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { User } from "@/lib/types";
import { Button } from "../ui/Button";
import { Field, Input } from "../ui/Input";
import { Callout } from "../ui/Callout";
import clsx from "clsx";

function strength(pw: string): { score: number; label: string } {
  let score = 0;
  if (pw.length >= 10) score++;
  if (pw.length >= 14) score++;
  if (/[a-z]/.test(pw) && /[A-Z]/.test(pw)) score++;
  if (/\d/.test(pw) && /[^A-Za-z0-9]/.test(pw)) score++;
  return { score, label: ["Too short", "Okay", "Good", "Strong", "Excellent"][score] };
}

export function AdminStep({ onDone }: { onDone: (u: User) => void }) {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const create = useMutation({ mutationFn: () => api.createAdmin({ name: name.trim(), email: email.trim(), password }), onSuccess: (r) => onDone(r.user) });
  const s = strength(password);
  const tooShort = password.length > 0 && password.length < 10;

  return (
    <form
      className="space-y-4"
      onSubmit={(e) => {
        e.preventDefault();
        if (password.length >= 10) create.mutate();
      }}
    >
      <Field label="Your name" htmlFor="admin-name">
        <Input id="admin-name" autoComplete="name" value={name} onChange={(e) => setName(e.target.value)} required autoFocus />
      </Field>
      <Field label="Work email" htmlFor="admin-email">
        <Input id="admin-email" type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
      </Field>
      <Field
        label="Password"
        htmlFor="admin-password"
        error={tooShort ? "Use at least 10 characters." : null}
        aside={password && <span className={clsx("text-[12px]", s.score >= 3 ? "text-success" : s.score >= 1 ? "text-warning" : "text-danger")}>{s.label}</span>}
      >
        <Input id="admin-password" type="password" autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} required minLength={10} />
        <div className="mt-2 grid grid-cols-4 gap-1" aria-hidden>
          {[0, 1, 2, 3].map((i) => (
            <span
              key={i}
              className={clsx(
                "h-1 rounded-full transition-colors duration-150",
                i < s.score ? (s.score >= 3 ? "bg-success" : "bg-warning") : "bg-surface-2",
              )}
            />
          ))}
        </div>
      </Field>
      {create.isError && <Callout tone="danger">{create.error.message}</Callout>}
      <Button type="submit" size="lg" loading={create.isPending} className="w-full sm:w-auto">
        Create admin account
      </Button>
    </form>
  );
}
