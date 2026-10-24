import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, RefreshCw } from "lucide-react";
import clsx from "clsx";
import { api } from "@/lib/api";
import { Field, Input, Select } from "../ui/Input";
import { Spinner } from "../ui/Spinner";

const CUSTOM = "__custom__";

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

/**
 * Model dropdown for one provider. Lists the models the provider's API actually
 * offers for this key (live), falling back to curated suggestions. Any other id
 * can still be entered via "Custom model…".
 */
export function ModelPicker({
  provider,
  providerLabel,
  apiKey,
  baseUrl,
  hasStoredKey,
  value,
  onChange,
}: {
  provider: string;
  providerLabel: string;
  apiKey: string;
  baseUrl: string;
  hasStoredKey: boolean;
  value: string;
  onChange: (model: string) => void;
}) {
  // Only query with a typed key once it looks complete, and not on every keystroke.
  const key = useDebounced(apiKey.trim().length >= 20 ? apiKey.trim() : "", 600);
  const url = useDebounced(baseUrl.trim(), 600);

  const models = useQuery({
    queryKey: ["llm-models", provider, key, url, hasStoredKey],
    queryFn: () => api.llmModels({ provider, ...(key ? { api_key: key } : {}), ...(url ? { base_url: url } : {}) }),
    // Cache successful live lists; never cache a fallback/failure, so a fixed key or
    // provider-side change is picked up on the next focus, mount, or keystroke.
    staleTime: (q) => (q.state.data?.source === "live" ? 5 * 60_000 : 0),
    gcTime: 5 * 60_000,
    refetchOnWindowFocus: true,
    retry: false,
  });

  const options = useMemo(() => models.data?.models ?? [], [models.data]);
  const inList = options.some((m) => m.id === value);
  const [custom, setCustom] = useState(false);
  const showCustom = custom || (!!value && options.length > 0 && !inList);

  // When a fresh list arrives and nothing usable is selected yet, pick the provider default.
  useEffect(() => {
    if (!models.data || value) return;
    const preferred = options.find((m) => m.id === models.data.default_model) ?? options[0];
    if (preferred) onChange(preferred.id);
  }, [models.data, options, value, onChange]);

  const status = models.isFetching ? (
    <span className="inline-flex items-center gap-1.5 text-muted">
      <Spinner className="h-3 w-3" label="Loading models" /> Loading models from {providerLabel}…
    </span>
  ) : models.data?.source === "live" ? (
    <span className="inline-flex items-center gap-1.5 text-success">
      <CheckCircle2 className="h-3.5 w-3.5" aria-hidden /> {options.length} models available to your key
    </span>
  ) : models.data?.message ? (
    <span className="inline-flex items-center gap-1.5 text-warning">
      <AlertTriangle className="h-3.5 w-3.5" aria-hidden /> {models.data.message} Showing suggested models.
    </span>
  ) : (
    <span className="text-muted">Suggested models. Add your API key to load every model {providerLabel} offers you.</span>
  );

  return (
    <Field
      label="Model"
      htmlFor="llm-model"
      help={status}
      aside={
        <button
          type="button"
          onClick={() => models.refetch()}
          disabled={models.isFetching}
          className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[12px] text-muted hover:bg-surface-2 hover:text-text disabled:opacity-50"
          aria-label="Refresh model list"
        >
          <RefreshCw className={clsx("h-3 w-3", models.isFetching && "animate-spin")} aria-hidden /> Refresh
        </button>
      }
    >
      <div className="space-y-2">
        <Select
          id="llm-model"
          value={showCustom ? CUSTOM : value}
          onChange={(e) => {
            if (e.target.value === CUSTOM) {
              setCustom(true);
              return;
            }
            setCustom(false);
            onChange(e.target.value);
          }}
          className="w-full"
        >
          {!value && !showCustom && <option value="">Select a model…</option>}
          {options.map((m) => (
            <option key={m.id} value={m.id}>
              {m.label && m.label !== m.id ? `${m.label} (${m.id})` : m.id}
              {m.id === models.data?.default_model ? ", recommended" : ""}
            </option>
          ))}
          <option value={CUSTOM}>Custom model…</option>
        </Select>
        {showCustom && (
          <Input
            aria-label="Custom model id"
            placeholder="Exact model id, e.g. my-finetuned-model"
            value={value}
            onChange={(e) => onChange(e.target.value)}
            required
            spellCheck={false}
            autoFocus={custom}
          />
        )}
      </div>
    </Field>
  );
}
