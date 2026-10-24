import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronRight, Database, RefreshCw, Search, Table2 } from "lucide-react";
import clsx from "clsx";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { formatNumber } from "@/lib/format";
import { useMe } from "@/hooks/useSession";
import { PageHeader } from "@/components/ui/PageHeader";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Spinner } from "@/components/ui/Spinner";
import { Callout } from "@/components/ui/Callout";
import { EmptyState } from "@/components/ui/EmptyState";

export default function DataPage() {
  const isAdmin = useMe().data?.role === "admin";
  const qc = useQueryClient();
  const schema = useQuery({ queryKey: ["schema"], queryFn: api.schema });
  const [q, setQ] = useState("");
  const [open, setOpen] = useState<Set<string>>(new Set());

  const refresh = useMutation({
    mutationFn: api.refreshSchema,
    onSuccess: (d) => {
      qc.setQueryData(["schema"], d);
      qc.invalidateQueries({ queryKey: ["suggestions"] });
      toast.success("Schema refreshed");
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const tables = useMemo(() => {
    const term = q.trim().toLowerCase();
    const all = schema.data?.tables ?? [];
    if (!term) return all;
    return all
      .map((t) => {
        const tableHit = t.name.toLowerCase().includes(term);
        const cols = t.columns.filter((c) => c.name.toLowerCase().includes(term));
        return tableHit ? t : cols.length ? { ...t, columns: cols } : null;
      })
      .filter((t): t is NonNullable<typeof t> => t !== null);
  }, [schema.data, q]);

  const toggle = (name: string) =>
    setOpen((s) => {
      const n = new Set(s);
      n.has(name) ? n.delete(name) : n.add(name);
      return n;
    });

  return (
    <div className="mx-auto max-w-4xl px-4 py-8 sm:px-6">
      <PageHeader
        title="Data"
        description={schema.data ? <>Tables Inquira can query in <span className="font-medium text-text">{schema.data.datasource}</span>.</> : "Tables Inquira can query."}
        action={
          isAdmin && (
            <Button variant="secondary" onClick={() => refresh.mutate()} loading={refresh.isPending}>
              <RefreshCw className="h-3.5 w-3.5" /> Refresh schema
            </Button>
          )
        }
      />
      {schema.isPending ? (
        <Spinner className="h-5 w-5 text-muted" />
      ) : schema.isError ? (
        <Callout tone="danger">{schema.error.message}</Callout>
      ) : schema.data.tables.length === 0 ? (
        <Card>
          <EmptyState icon={Database} title="No tables found" description="Connect a data source in Settings, then refresh the schema." />
        </Card>
      ) : (
        <>
          <div className="relative mb-4">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" aria-hidden />
            <Input aria-label="Search tables and columns" placeholder="Search tables and columns…" className="pl-9" value={q} onChange={(e) => setQ(e.target.value)} />
          </div>
          <Card className="divide-y divide-border overflow-hidden">
            {tables.map((t) => {
              const expanded = open.has(t.name) || !!q.trim();
              return (
                <div key={t.name}>
                  <button
                    type="button"
                    onClick={() => toggle(t.name)}
                    aria-expanded={expanded}
                    className="flex w-full items-center gap-3 px-4 py-3 text-left transition-colors duration-150 hover:bg-surface-2/60"
                  >
                    <ChevronRight className={clsx("h-4 w-4 text-muted transition-transform duration-150", expanded && "rotate-90")} aria-hidden />
                    <Table2 className="h-4 w-4 text-accent" aria-hidden />
                    <span className="flex-1 truncate font-mono text-[13px] font-medium">{t.name}</span>
                    <span className="hidden text-[12px] text-muted sm:inline">{t.columns.length} columns</span>
                    {t.row_count != null && <Badge className="tabular-nums">{formatNumber(t.row_count)} rows</Badge>}
                  </button>
                  {expanded && (
                    <ul className="grid gap-x-6 bg-surface-2/40 px-4 py-3 pl-[52px] sm:grid-cols-2">
                      {t.columns.map((c) => (
                        <li key={c.name} className="flex items-center justify-between gap-3 py-1 text-[13px]">
                          <span className="truncate font-mono">{c.name}</span>
                          <span className="shrink-0 font-mono text-[11px] uppercase text-muted">{c.type}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              );
            })}
            {tables.length === 0 && <p className="px-4 py-6 text-center text-[13px] text-muted">No tables or columns match “{q}”.</p>}
          </Card>
        </>
      )}
    </div>
  );
}
