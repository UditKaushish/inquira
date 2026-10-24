import { Download } from "lucide-react";
import clsx from "clsx";
import type { ResultPayload } from "@/lib/types";
import { downloadText, formatCell, humanize, toCSV } from "@/lib/format";
import { Button } from "../ui/Button";

const MAX_ROWS = 500;

export function ResultTable({ result, filename = "inquira-result" }: { result: ResultPayload; filename?: string }) {
  const { columns, rows } = result;
  const shown = rows.slice(0, MAX_ROWS);
  return (
    <div>
      <div className="max-h-[440px] overflow-auto rounded-lg hairline">
        <table className="w-full border-collapse text-[13px]">
          <thead className="sticky top-0 z-10 bg-surface-2">
            <tr>
              {columns.map((c) => (
                <th
                  key={c.name}
                  scope="col"
                  className={clsx(
                    "whitespace-nowrap border-b border-border px-3 py-2 text-[12px] font-medium text-muted",
                    c.type === "number" ? "text-right" : "text-left",
                  )}
                >
                  {humanize(c.name)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {shown.map((r, i) => (
              <tr key={i} className="border-b border-border/60 last:border-0 hover:bg-surface-2/60">
                {r.map((cell, j) => {
                  const col = columns[j];
                  const text = formatCell(cell, col?.type);
                  return (
                    <td
                      key={j}
                      title={text}
                      className={clsx(
                        "max-w-[320px] truncate whitespace-nowrap px-3 py-2",
                        col?.type === "number" ? "text-right tabular-nums" : "text-left",
                        cell === null && "text-muted",
                      )}
                    >
                      {text}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="mt-2 flex items-center justify-between gap-2">
        <p className="text-[12px] text-muted">
          {rows.length > MAX_ROWS ? `Showing ${MAX_ROWS} of ${rows.length} rows` : `${rows.length} row${rows.length === 1 ? "" : "s"}`}
          {result.truncated && " · result truncated by row limit"}
        </p>
        <Button variant="ghost" size="sm" onClick={() => downloadText(`${filename}.csv`, "text/csv;charset=utf-8", toCSV(columns, rows))}>
          <Download className="h-3.5 w-3.5" /> CSV
        </Button>
      </div>
    </div>
  );
}
