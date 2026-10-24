import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, BarChart3, MessageSquareText, ShieldCheck, Sparkles } from "lucide-react";
import { api } from "@/lib/api";
import { useMe, useSessionActions, useSetupStatus } from "@/hooks/useSession";
import { Logo } from "@/components/ui/Logo";
import { Button } from "@/components/ui/Button";
import { Spinner } from "@/components/ui/Spinner";
import { StepRail, type RailStep } from "@/components/onboarding/StepRail";
import { AdminStep } from "@/components/onboarding/AdminStep";
import { DatasourceForm } from "@/components/settings/DatasourceForm";
import { LlmForm } from "@/components/settings/LlmForm";

const STEPS: RailStep[] = [
  { id: "welcome", title: "Welcome", hint: "What Inquira does" },
  { id: "admin", title: "Create admin", hint: "Your owner account" },
  { id: "data", title: "Connect data", hint: "Warehouse or demo" },
  { id: "ai", title: "Connect AI", hint: "Bring your own model" },
  { id: "ready", title: "You're ready", hint: "Ask your first question" },
];

export default function SetupPage() {
  const status = useSetupStatus();
  const me = useMe();
  const { setUser, refreshSetup } = useSessionActions();
  const navigate = useNavigate();
  const settings = useQuery({ queryKey: ["settings"], queryFn: api.settings, enabled: !!me.data });

  const completed = useMemo(() => {
    const s = new Set<string>();
    if (status.data && !status.data.needs_admin) s.add("welcome").add("admin");
    if (status.data?.has_datasource) s.add("data");
    if (status.data?.has_llm) s.add("ai");
    return s;
  }, [status.data]);

  const initial = useMemo(() => {
    if (!status.data) return 0;
    if (status.data.needs_admin) return 0;
    if (!status.data.has_datasource) return 2;
    if (!status.data.has_llm) return 3;
    return 4;
  }, [status.data]);

  const [step, setStep] = useState<number | null>(null);
  useEffect(() => {
    if (step === null && status.data) setStep(initial);
  }, [initial, status.data, step]);

  if (step === null) {
    return (
      <div className="grid h-full place-items-center">
        <Spinner className="h-5 w-5 text-muted" />
      </div>
    );
  }

  const go = (n: number) => {
    setStep(n);
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  return (
    <div className="min-h-full bg-bg">
      <div className="mx-auto grid min-h-full max-w-6xl md:grid-cols-[280px_1fr]">
        <aside className="border-b border-border px-6 py-6 md:min-h-screen md:border-b-0 md:border-r md:py-10">
          <Logo />
          <div className="mt-8 hidden md:block">
            <StepRail steps={STEPS} current={step} completed={completed} />
          </div>
          <div className="mt-4 md:hidden">
            <div className="flex items-center justify-between text-[12px] text-muted">
              <span>
                Step {step + 1} of {STEPS.length}
              </span>
              <span>{STEPS[step].title}</span>
            </div>
            <div className="mt-2 h-1 rounded-full bg-surface-2">
              <div className="h-1 rounded-full bg-accent transition-all duration-300" style={{ width: `${((step + 1) / STEPS.length) * 100}%` }} />
            </div>
          </div>
        </aside>

        <main className="px-6 py-10 sm:px-10 md:py-16">
          <div key={step} className="mx-auto max-w-xl animate-fade-in">
            {step === 0 && (
              <StepFrame
                eyebrow="Welcome to Inquira"
                title="Ask your data anything. Get answers you can trust."
                description="Inquira turns plain-English questions into validated, read-only SQL, runs it on your warehouse, and explains the result. Setup takes about two minutes."
              >
                <ul className="mb-8 space-y-4">
                  <Feature icon={MessageSquareText} title="Plain-English questions" text="No SQL required. Follow-ups keep their context." />
                  <Feature icon={ShieldCheck} title="Validated, read-only SQL" text="Every query is parsed and checked before it runs. Writes are impossible." />
                  <Feature icon={BarChart3} title="Charts with explanations" text="The right chart, the raw table, and the exact SQL, all side by side." />
                </ul>
                <Button size="lg" onClick={() => go(status.data?.needs_admin ? 1 : me.data ? 2 : 1)}>
                  Get started <ArrowRight className="h-4 w-4" />
                </Button>
              </StepFrame>
            )}

            {step === 1 && (
              <StepFrame eyebrow="Step 2 of 5" title="Create your admin account" description="You'll own this workspace and can invite teammates later.">
                {status.data?.needs_admin ? (
                  <AdminStep
                    onDone={(u) => {
                      setUser(u);
                      refreshSetup();
                      go(2);
                    }}
                  />
                ) : (
                  <Button onClick={() => go(2)}>
                    Admin already created. Continue <ArrowRight className="h-4 w-4" />
                  </Button>
                )}
              </StepFrame>
            )}

            {step === 2 && (
              <StepFrame
                eyebrow="Step 3 of 5"
                title="Connect your data"
                description="Start with the demo dataset to explore, or connect your own warehouse. You can change this anytime in Settings."
              >
                <DatasourceForm current={settings.data?.datasource} onSaved={() => go(status.data?.has_llm ? 4 : 3)} />
              </StepFrame>
            )}

            {step === 3 && (
              <StepFrame
                eyebrow="Step 4 of 5"
                title="Connect an AI model"
                description="Bring your own key. Calls go from your Inquira server straight to the provider; the key never reaches the browser."
              >
                <LlmForm current={settings.data?.llm} onSaved={() => go(4)} />
              </StepFrame>
            )}

            {step === 4 && <ReadyStep onBack={() => go(3)} onOpen={(q) => navigate("/app", { replace: true, state: q ? { ask: q } : null })} />}
          </div>
        </main>
      </div>
    </div>
  );
}

function StepFrame({ eyebrow, title, description, children }: { eyebrow: string; title: string; description: string; children: ReactNode }) {
  return (
    <section>
      <p className="text-[12px] font-medium uppercase tracking-wide text-accent">{eyebrow}</p>
      <h1 className="mt-2 text-2xl font-semibold tracking-tight sm:text-[28px] sm:leading-tight">{title}</h1>
      <p className="mt-3 text-[15px] leading-relaxed text-muted">{description}</p>
      <div className="mt-8">{children}</div>
    </section>
  );
}

function Feature({ icon: Icon, title, text }: { icon: typeof Sparkles; title: string; text: string }) {
  return (
    <li className="flex gap-3">
      <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-accent/12 text-accent">
        <Icon className="h-4 w-4" aria-hidden />
      </span>
      <div>
        <div className="text-sm font-medium">{title}</div>
        <div className="text-[13px] text-muted">{text}</div>
      </div>
    </li>
  );
}

function ReadyStep({ onOpen, onBack }: { onOpen: (q?: string) => void; onBack: () => void }) {
  const status = useSetupStatus();
  const suggestions = useQuery({ queryKey: ["suggestions"], queryFn: api.suggestions, enabled: !!status.data?.completed });
  const ready = !!status.data?.completed;

  return (
    <StepFrame
      eyebrow="Step 5 of 5"
      title={ready ? "You're all set" : "Almost there"}
      description={ready ? "Your workspace is ready. Try one of these to see Inquira in action." : "A data source and an AI model are both needed before you can ask questions."}
    >
      {ready ? (
        <>
          <div className="space-y-2">
            {suggestions.isPending
              ? [0, 1, 2].map((i) => <div key={i} className="h-12 animate-pulse rounded-xl bg-surface-2" />)
              : (suggestions.data?.questions ?? []).slice(0, 4).map((q) => (
                  <button
                    key={q}
                    type="button"
                    onClick={() => onOpen(q)}
                    className="group flex w-full items-center gap-3 rounded-xl bg-surface px-4 py-3 text-left text-sm hairline transition-colors duration-150 hover:border-accent/50"
                  >
                    <Sparkles className="h-4 w-4 shrink-0 text-accent" aria-hidden />
                    <span className="flex-1">{q}</span>
                    <ArrowRight className="h-4 w-4 text-muted transition-transform duration-150 group-hover:translate-x-0.5 group-hover:text-text" aria-hidden />
                  </button>
                ))}
          </div>
          <div className="mt-8">
            <Button size="lg" onClick={() => onOpen()}>
              Open workspace <ArrowRight className="h-4 w-4" />
            </Button>
          </div>
        </>
      ) : (
        <Button variant="secondary" onClick={onBack}>
          Go back
        </Button>
      )}
    </StepFrame>
  );
}
