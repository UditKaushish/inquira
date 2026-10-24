import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot, Cpu, Gem, Lock, Sparkle } from "lucide-react";
import { api } from "@/lib/api";
import type { LlmSettings, TestResult } from "@/lib/types";
import { formatDuration } from "@/lib/format";
import { Button } from "../ui/Button";
import { Field, Input } from "../ui/Input";
import { Badge } from "../ui/Badge";
import { Callout } from "../ui/Callout";
import { ModelPicker } from "./ModelPicker";

const KEY_PREFIXES: Array<[string, string]> = [["sk-ant-", "anthropic"], ["AIza", "gemini"], ["sk-", "openai"]];

function detectKeyProvider(key: string): string | null {
  const k = key.trim();
  return KEY_PREFIXES.find(([prefix]) => k.startsWith(prefix))?.[1] ?? null;
}
import { Spinner } from "../ui/Spinner";
import { ProviderCard } from "./ProviderCard";

const icons: Record<string, typeof Bot> = { gemini: Gem, anthropic: Sparkle, openai: Bot, openai_compatible: Cpu };

export function LlmForm({ current, onSaved, submitLabel = "Save and continue" }: { current?: LlmSettings | null; onSaved: (l: LlmSettings) => void; submitLabel?: string }) {
  const qc = useQueryClient();
  const providers = useQuery({ queryKey: ["providers"], queryFn: api.providers, staleTime: Infinity });
  const [provider, setProvider] = useState(current?.provider ?? "");
  const [model, setModel] = useState(current?.model ?? "");
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState(current?.base_url ?? "");
  const [test, setTest] = useState<TestResult | null>(null);
  const [switchedNote, setSwitchedNote] = useState<string | null>(null);
  const pendingKey = useRef<string | null>(null);

  const list = providers.data?.llm ?? [];
  const spec = list.find((p) => p.id === provider);
  const isCurrent = current?.provider === provider;
  const keyField = spec?.fields.find((f) => f.name === "api_key");
  const urlField = spec?.fields.find((f) => f.name === "base_url");

  useEffect(() => {
    if (!provider && list.length) setProvider(current?.provider ?? list[0].id);
  }, [list, provider, current]);

  useEffect(() => {
    if (!spec) return;
    setTest(null);
    setApiKey(pendingKey.current ?? "");
    pendingKey.current = null;
    if (isCurrent && current) {
      setModel(current.model);
      setBaseUrl(current.base_url ?? "");
    } else {
      setModel(spec.default_model ?? spec.models?.[0] ?? "");
      setBaseUrl("");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [provider, spec?.id]);

  const payload = () => ({
    provider,
    model: model.trim(),
    ...(apiKey.trim() ? { api_key: apiKey.trim() } : {}),
    ...(urlField && baseUrl.trim() ? { base_url: baseUrl.trim() } : {}),
  });

  const testMut = useMutation({ mutationFn: () => api.testLlm(payload()), onSuccess: setTest, onError: (e: Error) => setTest({ ok: false, message: e.message }) });
  const save = useMutation({
    mutationFn: () => api.saveLlm(payload()),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ["settings"] });
      qc.invalidateQueries({ queryKey: ["setup-status"] });
      qc.invalidateQueries({ queryKey: ["suggestions"] });
      onSaved(r.llm);
    },
  });

  if (providers.isPending) return <Spinner className="h-5 w-5 text-muted" />;
  if (providers.isError) return <Callout tone="danger">{providers.error.message}</Callout>;

  const keyRequired = !!keyField?.required && !(isCurrent && current?.has_key);

  return (
    <form
      className="space-y-6"
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate();
      }}
    >
      <div className="grid gap-2.5 sm:grid-cols-2" role="radiogroup" aria-label="AI provider">
        {list.map((p) => {
          const Icon = icons[p.id] ?? Bot;
          return (
            <ProviderCard
              key={p.id}
              selected={provider === p.id}
              onSelect={() => setProvider(p.id)}
              title={p.label}
              description={p.description}
              icon={<Icon className="h-4 w-4" />}
              badge={current?.provider === p.id ? <Badge tone="success">Active</Badge> : undefined}
            />
          );
        })}
      </div>

      {spec && (
        <div className="space-y-4">
          {keyField && (
            <Field
              label={keyField.required ? keyField.label : `${keyField.label} (optional)`}
              htmlFor="llm-key"
              help={
                <span className="inline-flex items-center gap-1">
                  <Lock className="h-3 w-3" aria-hidden /> Encrypted at rest. Never sent back to the browser.
                </span>
              }
            >
              <Input
                id="llm-key"
                type="password"
                autoComplete="new-password"
                spellCheck={false}
                value={apiKey}
                onChange={(e) => {
                  setTest(null);
                  setSwitchedNote(null);
                  const value = e.target.value;
                  const owner = detectKeyProvider(value);
                  if (owner && owner !== provider && provider !== "openai_compatible" && list.some((p) => p.id === owner)) {
                    // A pasted key that clearly belongs to another provider: switch instead of failing later.
                    pendingKey.current = value;
                    setProvider(owner);
                    setSwitchedNote(`That key belongs to ${list.find((p) => p.id === owner)?.label}, so we switched the provider for you.`);
                    return;
                  }
                  setApiKey(value);
                }}
                placeholder={isCurrent && current?.has_key ? "•••••••• (unchanged)" : keyField.placeholder}
                required={keyRequired}
              />
            </Field>
          )}
          {urlField && (
            <Field label={urlField.required ? urlField.label : `${urlField.label} (optional)`} htmlFor="llm-url" help={urlField.help}>
              <Input id="llm-url" value={baseUrl} onChange={(e) => { setTest(null); setBaseUrl(e.target.value); }} placeholder={urlField.placeholder} required={urlField.required} spellCheck={false} />
            </Field>
          )}
          <ModelPicker
            provider={provider}
            providerLabel={spec.label}
            apiKey={apiKey}
            baseUrl={baseUrl}
            hasStoredKey={isCurrent && !!current?.has_key}
            value={model}
            onChange={(m) => { setTest(null); setModel(m); }}
          />

        </div>
      )}

      {test && (
        <Callout tone={test.ok ? "success" : "danger"}>
          {test.ok ? `${test.message}${test.latency_ms != null ? ` · ${formatDuration(test.latency_ms)}` : ""}` : test.message}
        </Callout>
      )}
      {switchedNote && <Callout tone="info">{switchedNote}</Callout>}
      {save.isError && <Callout tone="danger">{save.error.message}</Callout>}

      <div className="flex flex-wrap gap-2">
        <Button variant="secondary" onClick={() => testMut.mutate()} loading={testMut.isPending} disabled={!model.trim() || (keyRequired && !apiKey.trim())}>
          Test
        </Button>
        <Button type="submit" loading={save.isPending} disabled={!model.trim()}>
          {submitLabel}
        </Button>
      </div>
    </form>
  );
}
