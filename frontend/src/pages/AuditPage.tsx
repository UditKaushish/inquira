import { useQuery } from "@tanstack/react-query";
import { ScrollText } from "lucide-react";
import { api } from "@/lib/api";
import { formatDuration, formatNumber, timeAgo } from "@/lib/format";
import { PageHeader } from "@/components/ui/PageHeader";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Spinner } from "@/components/ui/Spinner";
import { Callout } from "@/components/ui/Callout";
import { EmptyState } from "@/components/ui/EmptyState";

export default function AuditPage() {
  const audit = useQuery({ queryKey: ["audit"], queryFn: () => api.audit(100), refetchInterval: 30_000 });

  return (
    <div className="mx-auto max-w-5xl px-4 py-8 sm:px-6">
      <PageHeader title="Audit log" description="Every question asked in this workspace, who asked it, and the SQL that ran." />
      {audit.isPending ? (
        <Spinner className="h-5 w-5 text-muted" />
      ) : audit.isError ? (
        <Callout tone="danger">{audit.error.message}</Callout>
      ) : audit.data.events.length === 0 ? (
        <Card>
          <EmptyState icon={ScrollText} title="No activity yet" description="Questions will show up here as your team uses Inquira." />
        </Card>
      ) : (
        <Card className="overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-[13px]">
              <thead className="bg-surface-2 text-left text-[12px] text-muted">
                <tr>
                  <th scope="col" className="px-4 py-2 font-medium">Question</th>
                  <th scope="col" className="px-4 py-2 font-medium">User</th>
                  <th scope="col" className="px-4 py-2 font-medium">Status</th>
                  <th scope="col" className="px-4 py-2 text-right font-medium">Rows</th>
                  <th scope="col" className="px-4 py-2 text-right font-medium">Time</th>
                  <th scope="col" className="px-4 py-2 font-medium">When</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {audit.data.events.map((e) => (
                  <tr key={e.id} className="align-top">
                    <td className="max-w-[360px] px-4 py-3">
                      <div className="line-clamp-2">{e.question}</div>
                      {e.sql && (
                        <details className="mt-1">
                          <summary className="cursor-pointer text-[12px] text-muted hover:text-text">SQL</summary>
                          <pre className="mt-1 max-h-48 overflow-auto rounded-md bg-surface-2 p-2 font-mono text-[11.5px] [font-variant-ligatures:none]">{e.sql}</pre>
                        </details>
                      )}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-muted">{e.user_email}</td>
                    <td className="px-4 py-3">
                      <Badge tone={e.status === "ok" ? "success" : "danger"}>{e.status}</Badge>
                    </td>
                    <td className="px-4 py-3 text-right tabular-nums">{e.row_count != null ? formatNumber(e.row_count) : "—"}</td>
                    <td className="px-4 py-3 text-right tabular-nums">{e.elapsed_ms != null ? formatDuration(e.elapsed_ms) : "—"}</td>
                    <td className="whitespace-nowrap px-4 py-3 text-muted">{timeAgo(e.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  );
}
