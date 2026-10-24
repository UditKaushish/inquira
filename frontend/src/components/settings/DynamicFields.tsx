import type { ProviderField } from "@/lib/types";
import { Field, Input } from "../ui/Input";

export function DynamicFields({
  idPrefix,
  fields,
  values,
  onChange,
  secretPlaceholder,
}: {
  idPrefix: string;
  fields: ProviderField[];
  values: Record<string, string>;
  onChange: (name: string, value: string) => void;
  secretPlaceholder?: string;
}) {
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      {fields.map((f) => {
        const id = `${idPrefix}-${f.name}`;
        const wide = f.type !== "number" && (f.secret || /url|account|path|host|database|dsn/i.test(f.name));
        return (
          <div key={f.name} className={wide ? "sm:col-span-2" : undefined}>
            <Field label={f.required ? f.label : `${f.label} (optional)`} htmlFor={id} help={f.help}>
              <Input
                id={id}
                type={f.secret || f.type === "password" ? "password" : f.type === "number" ? "number" : "text"}
                autoComplete={f.secret ? "new-password" : "off"}
                spellCheck={false}
                placeholder={f.secret && secretPlaceholder ? secretPlaceholder : f.placeholder}
                value={values[f.name] ?? ""}
                onChange={(e) => onChange(f.name, e.target.value)}
                required={f.required && !(f.secret && secretPlaceholder)}
              />
            </Field>
          </div>
        );
      })}
    </div>
  );
}
