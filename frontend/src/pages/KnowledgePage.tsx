import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BookOpen, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import type { KnowledgeKind } from "@/lib/types";
import { timeAgo, formatNumber } from "@/lib/format";
import { useMe } from "@/hooks/useSession";
import { PageHeader } from "@/components/ui/PageHeader";
import { Button } from "@/components/ui/Button";
import { Field, Input, Select, Textarea } from "@/components/ui/Input";
import { Card, CardHeader } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Spinner } from "@/components/ui/Spinner";
import { Callout } from "@/components/ui/Callout";
import { EmptyState } from "@/components/ui/EmptyState";
import { useConfirm } from "@/components/ui/Dialog";

const kinds: { id: KnowledgeKind; label: string; placeholder: string }[] = [
  { id: "metric", label: "Metric definition", placeholder: "Revenue = SUM(order_items.price + order_items.freight_value) for orders that are not canceled." },
  { id: "glossary", label: "Glossary term", placeholder: "“GMV” means gross merchandise value, the same as revenue before refunds." },
  { id: "note", label: "Note", placeholder: "Join orders to customers on customer_id. Use customer_unique_id to count real people." },
];

const tone = { metric: "accent", glossary: "success", note: "neutral" } as const;

export default function KnowledgePage() {
  const isAdmin = useMe().data?.role === "admin";
  const qc = useQueryClient();
  const confirm = useConfirm();
  const docs = useQuery({ queryKey: ["knowledge"], queryFn: api.knowledge });
  const [title, setTitle] = useState("");
  const [kind, setKind] = useState<KnowledgeKind>("metric");
  const [content, setContent] = useState("");

  const add = useMutation({
    mutationFn: () => api.addKnowledge({ title: title.trim(), kind, content: content.trim() }),
    onSuccess: () => {
      setTitle("");
      setContent("");
      qc.invalidateQueries({ queryKey: ["knowledge"] });
      toast.success("Added to knowledge");
    },
  });
  const remove = useMutation({
    mutationFn: api.deleteKnowledge,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["knowledge"] }),
    onError: (e: Error) => toast.error(e.message),
  });

  return (
    <div className="mx-auto max-w-4xl px-4 py-8 sm:px-6">
      <PageHeader title="Knowledge" description="Teach Inquira your business language: metric definitions, glossary terms and join rules. Relevant entries are used as context for every question." />

      {isAdmin && (
        <Card className="mb-6">
          <CardHeader title="Add knowledge" description="Short, precise entries work best." />
          <form
            className="space-y-4 p-5"
            onSubmit={(e) => {
              e.preventDefault();
              add.mutate();
            }}
          >
            <div className="grid gap-4 sm:grid-cols-[1fr_200px]">
              <Field label="Title" htmlFor="kn-title">
                <Input id="kn-title" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Revenue" required />
              </Field>
              <Field label="Type" htmlFor="kn-kind">
                <Select id="kn-kind" value={kind} onChange={(e) => setKind(e.target.value as KnowledgeKind)}>
                  {kinds.map((k) => (
                    <option key={k.id} value={k.id}>
                      {k.label}
                    </option>
                  ))}
                </Select>
              </Field>
            </div>
            <Field label="Content" htmlFor="kn-content">
              <Textarea id="kn-content" rows={4} value={content} onChange={(e) => setContent(e.target.value)} placeholder={kinds.find((k) => k.id === kind)?.placeholder} required />
            </Field>
            {add.isError && <Callout tone="danger">{add.error.message}</Callout>}
            <Button type="submit" loading={add.isPending} disabled={!title.trim() || !content.trim()}>
              Add entry
            </Button>
          </form>
        </Card>
      )}

      {docs.isPending ? (
        <Spinner className="h-5 w-5 text-muted" />
      ) : docs.isError ? (
        <Callout tone="danger">{docs.error.message}</Callout>
      ) : docs.data.documents.length === 0 ? (
        <Card>
          <EmptyState icon={BookOpen} title="No knowledge yet" description="Add definitions so answers match how your team talks about the business." />
        </Card>
      ) : (
        <Card className="divide-y divide-border">
          {docs.data.documents.map((d) => (
            <div key={d.id} className="flex items-center gap-3 px-4 py-3">
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="truncate text-sm font-medium">{d.title}</span>
                  <Badge tone={tone[d.kind]}>{kinds.find((k) => k.id === d.kind)?.label ?? d.kind}</Badge>
                </div>
                <div className="mt-0.5 text-[12px] text-muted">
                  {formatNumber(d.chars)} characters · added {timeAgo(d.created_at)}
                </div>
              </div>
              {isAdmin && (
                <Button
                  variant="ghost"
                  size="icon"
                  aria-label={`Delete ${d.title}`}
                  onClick={async () => {
                    if (await confirm({ title: "Delete entry?", description: `“${d.title}” will no longer be used as context.`, confirmLabel: "Delete", danger: true })) remove.mutate(d.id);
                  }}
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              )}
            </div>
          ))}
        </Card>
      )}
    </div>
  );
}
