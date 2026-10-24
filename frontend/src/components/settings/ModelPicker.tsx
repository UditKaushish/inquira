import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, Check, ChevronsUpDown, PenLine, RefreshCw, Search, ShieldCheck } from "lucide-react";
import clsx from "clsx";
import { api } from "@/lib/api";
import type { ModelInfo } from "@/lib/types";
import { Field, Input } from "../ui/Input";
import { Badge } from "../ui/Badge";
import { Spinner } from "../ui/Spinner";

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

type Tag = "recommended" | "preview" | "alias" | "open";

function tagsFor(m: ModelInfo, defaultModel?: string): Tag[] {
  const id = m.id.toLowerCase();
  const tags: Tag[] = [];
  if (m.id === defaultModel) tags.push("recommended");
  if (/preview|exp/.test(id)) tags.push("preview");
  if (/latest/.test(id)) tags.push("alias");
  if (/^gemma|llama|qwen|mistral/.test(id)) tags.push("open");
  return tags;
}

const TAG_UI: Record<Tag, { label: string; tone: "accent" | "warning" | "neutral" | "success" }> = {
  recommended: { label: "Recommended", tone: "accent" },
  preview: { label: "Preview", tone: "warning" },
  alias: { label: "Auto-updating", tone: "neutral" },
  open: { label: "Open model", tone: "success" },
};

const CUSTOM = "__custom__";

/**
 * Searchable model picker. Lists only the models the provider confirmed this key can call
 * (the server probes each one), grouped into stable and experimental, with a custom-id escape hatch.
 * Implements the ARIA combobox + listbox pattern: arrows move, Enter selects, Esc closes.
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
  const key = useDebounced(apiKey.trim().length >= 20 ? apiKey.trim() : "", 600);
  const url = useDebounced(baseUrl.trim(), 600);
  const forceRefresh = useRef(false);

  const models = useQuery({
    queryKey: ["llm-models", provider, key, url, hasStoredKey],
    queryFn: () => {
      const refresh = forceRefresh.current;
      forceRefresh.current = false;
      return api.llmModels({ provider, refresh, ...(key ? { api_key: key } : {}), ...(url ? { base_url: url } : {}) });
    },
    // Cache verified lists; never cache a fallback, so a fixed key is re-checked promptly.
    staleTime: (q) => (q.state.data?.source === "live" ? 5 * 60_000 : 0),
    gcTime: 5 * 60_000,
    refetchOnWindowFocus: true,
    retry: false,
  });

  const options = useMemo(() => models.data?.models ?? [], [models.data]);
  const defaultModel = models.data?.default_model;
  const selected = options.find((m) => m.id === value);
  const [customMode, setCustomMode] = useState(false);
  const isCustom = customMode || (!!value && options.length > 0 && !selected);

  // A fresh verified list where the current choice isn't usable: switch to the recommended model.
  useEffect(() => {
    if (!models.data || models.isFetching || customMode) return;
    if (value && options.some((m) => m.id === value)) return;
    if (value && models.data.source !== "live") return; // can't verify: keep the manual choice
    const preferred = options.find((m) => m.id === defaultModel) ?? options[0];
    if (preferred && preferred.id !== value) onChange(preferred.id);
  }, [models.data, models.isFetching, options, value, defaultModel, customMode, onChange]);

  // ---- popover state
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const listId = useId();

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return q ? options.filter((m) => m.id.toLowerCase().includes(q) || (m.label ?? "").toLowerCase().includes(q)) : options;
  }, [options, query]);

  // Stable first (recommended at the top), then preview / auto-updating / open models.
  const groups = useMemo(() => {
    const experimental = (m: ModelInfo) => tagsFor(m).length > 0;
    const stable = filtered.filter((m) => !experimental(m));
    stable.sort((a, b) => Number(b.id === defaultModel) - Number(a.id === defaultModel));
    return [
      { title: "Stable", items: stable },
      { title: "Preview & experimental", items: filtered.filter(experimental) },
    ].filter((g) => g.items.length);
  }, [filtered, defaultModel]);
  const flat = useMemo(() => [...groups.flatMap((g) => g.items.map((m) => m.id)), CUSTOM], [groups]);

  useEffect(() => {
    if (!open) return;
    setActive(Math.max(0, flat.indexOf(value)));
    requestAnimationFrame(() => searchRef.current?.focus());
    const onDoc = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  useEffect(() => {
    if (open) document.getElementById(`${listId}-opt-${active}`)?.scrollIntoView({ block: "nearest" });
  }, [active, open, listId]);

  const choose = (id: string) => {
    if (id === CUSTOM) {
      setCustomMode(true);
    } else {
      setCustomMode(false);
      onChange(id);
    }
    setOpen(false);
    setQuery("");
    triggerRef.current?.focus();
  };

  const onListKey = (e: KeyboardEvent) => {
    const last = flat.length - 1;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((i) => Math.min(last, i + 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((i) => Math.max(0, i - 1));
    } else if (e.key === "Home") {
      e.preventDefault();
      setActive(0);
    } else if (e.key === "End") {
      e.preventDefault();
      setActive(last);
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (flat[active]) choose(flat[active]);
    } else if (e.key === "Escape") {
      e.preventDefault();
      setOpen(false);
      triggerRef.current?.focus();
    } else if (e.key === "Tab") {
      setOpen(false);
    }
  };

  const loading = models.isFetching;
  const status = loading ? (
    <span className="inline-flex items-center gap-1.5 text-muted">
      <Spinner className="h-3 w-3" label="Checking models" /> Checking which {providerLabel} models your key can use…
    </span>
  ) : models.data?.source === "live" ? (
    <span className="inline-flex items-center gap-1.5 text-success">
      <ShieldCheck className="h-3.5 w-3.5" aria-hidden /> {options.length} models verified for your key
    </span>
  ) : models.data?.message ? (
    <span className="inline-flex items-start gap-1.5 text-warning">
      <AlertTriangle className="mt-px h-3.5 w-3.5 shrink-0" aria-hidden /> {models.data.message} Showing suggested models.
    </span>
  ) : (
    <span className="text-muted">Suggested models. Add your API key to see exactly which ones your account can use.</span>
  );

  let optionIndex = -1;
  const renderOption = (m: ModelInfo) => {
    optionIndex += 1;
    const i = optionIndex;
    const isSel = m.id === value && !isCustom;
    const tags = tagsFor(m, defaultModel);
    const named = !!m.label && m.label !== m.id;
    return (
      <li
        key={m.id}
        id={`${listId}-opt-${i}`}
        role="option"
        aria-selected={isSel}
        onMouseEnter={() => setActive(i)}
        onMouseDown={(e) => e.preventDefault()}
        onClick={() => choose(m.id)}
        className={clsx(
          "flex cursor-pointer items-center gap-3 rounded-lg px-2.5 py-2 transition-colors duration-100",
          i === active && "bg-surface-2",
        )}
      >
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="truncate text-sm font-medium text-text">{named ? m.label : m.id}</span>
            {tags.map((t) => (
              <Badge key={t} tone={TAG_UI[t].tone}>
                {TAG_UI[t].label}
              </Badge>
            ))}
          </div>
          {named && <div className="truncate font-mono text-[11.5px] text-muted">{m.id}</div>}
        </div>
        <Check className={clsx("h-4 w-4 shrink-0 text-accent", isSel ? "opacity-100" : "opacity-0")} aria-hidden />
      </li>
    );
  };

  const customIndex = flat.length - 1;
  const selectedNamed = !!selected?.label && selected.label !== selected.id;

  return (
    <Field
      label="Model"
      htmlFor="llm-model"
      help={status}
      aside={
        <button
          type="button"
          onClick={() => {
            forceRefresh.current = true; // bypass the server-side availability cache
            models.refetch();
          }}
          disabled={loading}
          className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[12px] text-muted transition-colors hover:bg-surface-2 hover:text-text disabled:opacity-50"
          aria-label="Re-check available models"
        >
          <RefreshCw className={clsx("h-3 w-3", loading && "animate-spin")} aria-hidden /> Refresh
        </button>
      }
    >
      <div ref={rootRef} className="relative space-y-2">
        <button
          ref={triggerRef}
          id="llm-model"
          type="button"
          role="combobox"
          aria-haspopup="listbox"
          aria-expanded={open}
          aria-controls={listId}
          disabled={loading && !options.length}
          onClick={() => setOpen((o) => !o)}
          onKeyDown={(e) => {
            if (["ArrowDown", "ArrowUp", "Enter", " "].includes(e.key)) {
              e.preventDefault();
              setOpen(true);
            }
          }}
          className={clsx(
            "flex min-h-[44px] w-full items-center gap-3 rounded-lg bg-surface px-3 py-2 text-left hairline transition-colors duration-150",
            "hover:border-text/20 focus-visible:border-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/20",
            open && "border-accent ring-2 ring-accent/20",
            "disabled:cursor-wait disabled:opacity-60",
          )}
        >
          <div className="min-w-0 flex-1">
            {isCustom ? (
              <div className="flex items-center gap-2">
                <span className="truncate font-mono text-sm text-text">{value || "Enter a model id below"}</span>
                <Badge>Custom</Badge>
              </div>
            ) : selected ? (
              <div className="flex items-center gap-2">
                <span className="truncate text-sm font-medium text-text">{selectedNamed ? selected.label : selected.id}</span>
                {selectedNamed && <span className="hidden truncate font-mono text-[11.5px] text-muted sm:inline">{selected.id}</span>}
                {selected.id === defaultModel && <Badge tone="accent">Recommended</Badge>}
              </div>
            ) : (
              <span className="text-sm text-muted">{loading ? "Checking models…" : "Select a model"}</span>
            )}
          </div>
          {loading ? <Spinner className="h-4 w-4 text-muted" /> : <ChevronsUpDown className="h-4 w-4 shrink-0 text-muted" aria-hidden />}
        </button>

        {open && (
          <div className="absolute inset-x-0 top-[48px] z-50 overflow-hidden rounded-xl bg-surface shadow-xl ring-1 ring-border">
            <div className="flex items-center gap-2 border-b border-border px-3">
              <Search className="h-4 w-4 shrink-0 text-muted" aria-hidden />
              <input
                ref={searchRef}
                value={query}
                onChange={(e) => {
                  setQuery(e.target.value);
                  setActive(0);
                }}
                onKeyDown={onListKey}
                placeholder={`Search ${options.length} models…`}
                aria-label="Search models"
                aria-controls={listId}
                aria-activedescendant={`${listId}-opt-${active}`}
                className="h-11 w-full bg-transparent text-sm text-text placeholder:text-muted/70 focus:outline-none"
              />
            </div>
            <ul id={listId} role="listbox" aria-label={`${providerLabel} models`} className="max-h-[320px] overflow-y-auto p-1.5">
              {groups.map((g) => (
                <li key={g.title} role="presentation">
                  <div className="px-2.5 pb-1 pt-2 text-[11px] font-medium uppercase tracking-wide text-muted">{g.title}</div>
                  <ul role="presentation">{g.items.map(renderOption)}</ul>
                </li>
              ))}
              {!filtered.length && <li className="px-2.5 py-6 text-center text-sm text-muted">No models match “{query}”.</li>}
              <li role="presentation" className="mt-1 border-t border-border pt-1">
                <div
                  id={`${listId}-opt-${customIndex}`}
                  role="option"
                  aria-selected={isCustom}
                  onMouseEnter={() => setActive(customIndex)}
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={() => choose(CUSTOM)}
                  className={clsx(
                    "flex cursor-pointer items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm text-muted transition-colors duration-100",
                    active === customIndex && "bg-surface-2 text-text",
                  )}
                >
                  <PenLine className="h-4 w-4" aria-hidden /> Use a custom model id…
                </div>
              </li>
            </ul>
          </div>
        )}

        {isCustom && (
          <Input
            aria-label="Custom model id"
            placeholder="Exact model id, e.g. my-finetuned-model"
            value={value}
            onChange={(e) => onChange(e.target.value)}
            required
            spellCheck={false}
            autoFocus={customMode}
            className="h-10 px-3 font-mono"
          />
        )}
      </div>
    </Field>
  );
}
