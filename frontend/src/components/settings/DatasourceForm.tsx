import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Database, FileBox, Snowflake, Sparkles, Server, HardDrive } from "lucide-react";
import { api } from "@/lib/api";
import type { DatasourceSettings, TestResult } from "@/lib/types";
import { Button } from "../ui/Button";
import { Field, Input } from "../ui/Input";
import { Badge } from "../ui/Badge";
import { Callout } from "../ui/Callout";
import { Spinner } from "../ui/Spinner";
import { ProviderCard } from "./ProviderCard";
import { DynamicFields } from "./DynamicFields";

const icons: Record<string, typeof Database> = {
  demo: Sparkles,
  duckdb: FileBox,
  sqlite: HardDrive,
  postgres: Database,
  mysql: Server,
  snowflake: Snowflake,
};

export function DatasourceForm({ current, onSaved }: { current?: DatasourceSettings | null; onSaved: (d: DatasourceSettings) => void }) {
  const qc = useQueryClient();
  const providers = useQuery({ queryKey: ["providers"], queryFn: api.providers, staleTime: Infinity });
  const [kind, setKind] = useState<string>(current?.kind ?? "demo");
  const [name, setName] = useState(current?.name ?? "");
  const [config, setConfig] = useState<Record<string, string>>({});
  const [test, setTest] = useState<TestResult | null>(null);

  useEffect(() => {
    setTest(null);
    setConfig(current && current.kind === kind ? Object.fromEntries(Object.entries(current.details)) : {});
  }, [kind, current]);

  const done = (d: DatasourceSettings) => {
    qc.invalidateQueries({ queryKey: ["settings"] });
    qc.invalidateQueries({ queryKey: ["schema"] });
    qc.invalidateQueries({ queryKey: ["suggestions"] });
    qc.invalidateQueries({ queryKey: ["setup-status"] });
    onSaved(d);
  };

  const demo = useMutation({ mutationFn: api.useDemo, onSuccess: (r) => done(r.datasource) });
  const testMut = useMutation({ mutationFn: () => api.testDatasource({ kind, config }), onSuccess: setTest, onError: (e: Error) => setTest({ ok: false, message: e.message }) });
  const save = useMutation({
    mutationFn: () => api.saveDatasource({ kind, name: name.trim() || spec?.label || kind, config }),
    onSuccess: (r) => done(r.datasource),
  });

  if (providers.isPending) return <Spinner className="h-5 w-5 text-muted" />;
  if (providers.isError) return <Callout tone="danger">{providers.error.message}</Callout>;

  const list = providers.data.datasource;
  const spec = list.find((p) => p.id === kind);
  const ordered = [...list].sort((a, b) => (a.id === "demo" ? -1 : b.id === "demo" ? 1 : 0));
  const isCurrent = current?.kind === kind;

  return (
    <div className="space-y-6">
      <div className="grid gap-2.5 sm:grid-cols-2" role="radiogroup" aria-label="Data source type">
        {ordered.map((p) => {
          const Icon = icons[p.id] ?? Database;
          return (
            <div key={p.id} className={p.id === "demo" ? "sm:col-span-2" : undefined}>
              <ProviderCard
                selected={kind === p.id}
                onSelect={() => setKind(p.id)}
                title={p.id === "demo" ? "Demo dataset: Brazilian e-commerce" : p.label}
                description={p.id === "demo" ? "100k real orders from Olist: customers, products, payments, sellers. Ready in one click." : p.description}
                badge={p.id === "demo" ? <Badge tone="accent">Recommended</Badge> : current?.kind === p.id ? <Badge tone="success">Connected</Badge> : undefined}
                icon={<Icon className="h-4 w-4" />}
              />
            </div>
          );
        })}
      </div>

      {kind === "demo" ? (
        <div className="space-y-3">
          {demo.isError && <Callout tone="danger">{demo.error.message}</Callout>}
          <Button size="lg" onClick={() => demo.mutate()} loading={demo.isPending}>
            {isCurrent ? "Reload demo dataset" : "Use demo dataset"}
          </Button>
        </div>
      ) : spec ? (
        <form
          className="space-y-5"
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate();
          }}
        >
          <Field label="Display name" htmlFor="ds-name" help="Shown to your team, e.g. “Production warehouse”.">
            <Input id="ds-name" value={name} placeholder={spec.label} onChange={(e) => setName(e.target.value)} />
          </Field>
          <DynamicFields
            idPrefix={`ds-${kind}`}
            fields={spec.fields}
            values={config}
            onChange={(k, v) => {
              setTest(null);
              setConfig((c) => ({ ...c, [k]: v }));
            }}
            secretPlaceholder={isCurrent ? "•••••••• (unchanged)" : undefined}
          />
          <Callout>Inquira only runs read-only queries. For defence in depth, connect with a user that has SELECT-only access.</Callout>
          {test && (
            <Callout tone={test.ok ? "success" : "danger"}>
              {test.ok ? `${test.message}${test.table_count != null ? ` · ${test.table_count} tables found` : ""}` : test.message}
            </Callout>
          )}
          {save.isError && <Callout tone="danger">{save.error.message}</Callout>}
          <div className="flex flex-wrap gap-2">
            <Button variant="secondary" onClick={() => testMut.mutate()} loading={testMut.isPending}>
              Test connection
            </Button>
            <Button type="submit" loading={save.isPending}>
              Save and continue
            </Button>
          </div>
        </form>
      ) : null}
    </div>
  );
}
