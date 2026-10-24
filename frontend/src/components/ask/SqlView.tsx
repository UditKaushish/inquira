import { useState } from "react";
import { Check, Copy } from "lucide-react";
import type { ReactNode } from "react";

const KEYWORDS = new Set(
  ("select from where group by order having limit offset join left right inner outer full cross on as and or not in is null " +
    "case when then else end distinct union all with over partition desc asc between like ilike exists cast interval " +
    "true false date_trunc extract coalesce count sum avg min max round nullif lag lead row_number rank dense_rank filter qualify using")
    .split(" "),
);

function highlight(sql: string): ReactNode[] {
  const re = /(--[^\n]*|'(?:[^']|'')*'|"[^"]*"|\b\d+(?:\.\d+)?\b|\b[A-Za-z_][A-Za-z0-9_]*\b|[^\sA-Za-z0-9_'"-]+|\s+|-)/g;
  const out: ReactNode[] = [];
  let m: RegExpExecArray | null;
  let k = 0;
  while ((m = re.exec(sql))) {
    const t = m[0];
    if (t.startsWith("--")) out.push(<span key={k++} className="text-muted italic">{t}</span>);
    else if (t.startsWith("'")) out.push(<span key={k++} className="text-success">{t}</span>);
    else if (/^\d/.test(t)) out.push(<span key={k++} className="text-warning">{t}</span>);
    else if (KEYWORDS.has(t.toLowerCase())) out.push(<span key={k++} className="font-medium text-accent">{t}</span>);
    else out.push(t);
  }
  return out;
}

export function SqlView({ sql }: { sql: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(sql);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard blocked */
    }
  };
  return (
    <div className="relative">
      <button
        type="button"
        onClick={copy}
        className="absolute right-2 top-2 inline-flex h-7 items-center gap-1.5 rounded-md bg-surface px-2 text-[12px] text-muted hairline hover:text-text"
      >
        {copied ? <Check className="h-3.5 w-3.5 text-success" /> : <Copy className="h-3.5 w-3.5" />}
        {copied ? "Copied" : "Copy"}
      </button>
      <pre className="max-h-[420px] overflow-auto rounded-lg bg-surface-2 p-4 pr-24 font-mono text-[12.5px] leading-relaxed text-text [font-variant-ligatures:none]">
        <code>{highlight(sql)}</code>
      </pre>
    </div>
  );
}
