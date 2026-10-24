import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { PageHeader } from "@/components/ui/PageHeader";
import { Card, CardHeader } from "@/components/ui/Card";
import { Spinner } from "@/components/ui/Spinner";
import { Callout } from "@/components/ui/Callout";
import { Badge } from "@/components/ui/Badge";
import { LlmForm } from "@/components/settings/LlmForm";
import { DatasourceForm } from "@/components/settings/DatasourceForm";

export default function SettingsPage() {
  const settings = useQuery({ queryKey: ["settings"], queryFn: api.settings });

  return (
    <div className="mx-auto max-w-3xl px-4 py-8 sm:px-6">
      <PageHeader title="Settings" description="Manage the AI model and data source for this workspace." />
      {settings.isPending ? (
        <Spinner className="h-5 w-5 text-muted" />
      ) : settings.isError ? (
        <Callout tone="danger">{settings.error.message}</Callout>
      ) : (
        <div className="space-y-6">
          <Card>
            <CardHeader
              title="AI model"
              description={settings.data.llm ? <>Using <span className="font-mono text-text">{settings.data.llm.model}</span></> : "Not configured"}
              action={settings.data.llm ? <Badge tone="success">Connected</Badge> : <Badge tone="warning">Missing</Badge>}
            />
            <div className="p-5">
              <LlmForm current={settings.data.llm} submitLabel="Save" onSaved={() => toast.success("AI model saved")} />
            </div>
          </Card>
          <Card>
            <CardHeader
              title="Data source"
              description={settings.data.datasource ? settings.data.datasource.name : "Not configured"}
              action={settings.data.datasource ? <Badge tone="success">Connected</Badge> : <Badge tone="warning">Missing</Badge>}
            />
            <div className="p-5">
              <DatasourceForm current={settings.data.datasource} onSaved={() => toast.success("Data source saved")} />
            </div>
          </Card>
        </div>
      )}
    </div>
  );
}
