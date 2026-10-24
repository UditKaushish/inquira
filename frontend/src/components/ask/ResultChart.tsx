import { useMemo } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell as PieCell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { Chart, ResultPayload } from "@/lib/types";
import { formatCell, formatCompact, formatNumber, humanize } from "@/lib/format";
import { useChartPalette } from "@/hooks/useChartPalette";

type Row = Record<string, string | number | null>;

/** Resolve which columns to plot, falling back to sensible defaults. */
export function resolveChart(chart: Chart | null, result: ResultPayload): Chart {
  const numeric = result.columns.filter((c) => c.type === "number").map((c) => c.name);
  const dims = result.columns.filter((c) => c.type !== "number").map((c) => c.name);
  if (chart && chart.type !== "table") {
    const x = chart.x && result.columns.some((c) => c.name === chart.x) ? chart.x : dims[0];
    const y = (chart.y ?? []).filter((n) => numeric.includes(n));
    return { ...chart, x, y: y.length ? y : numeric.slice(0, 1) };
  }
  if (result.rows.length === 1 && numeric.length >= 1 && result.columns.length <= 2) return { type: "kpi", y: numeric.slice(0, 1) };
  if (dims.length && numeric.length && result.rows.length > 1) return { type: "bar", x: dims[0], y: numeric.slice(0, 1) };
  return { type: "table" };
}

export function isChartable(chart: Chart | null, result: ResultPayload): boolean {
  const c = resolveChart(chart, result);
  if (c.type === "table") return false;
  if (c.type === "kpi") return !!c.y?.length;
  return !!c.x && !!c.y?.length && result.rows.length > 0;
}

export function ResultChart({ chart, result }: { chart: Chart | null; result: ResultPayload }) {
  const palette = useChartPalette();
  const spec = resolveChart(chart, result);

  const data: Row[] = useMemo(
    () =>
      result.rows.slice(0, 200).map((r) => {
        const o: Row = {};
        result.columns.forEach((c, i) => {
          const v = r[i];
          o[c.name] = typeof v === "boolean" ? String(v) : (v as string | number | null);
        });
        return o;
      }),
    [result],
  );

  const ys = spec.y ?? [];
  const x = spec.x ?? "";
  const xType = result.columns.find((c) => c.name === x)?.type;

  if (spec.type === "kpi") {
    const col = ys[0];
    const v = col ? data[0]?.[col] : null;
    return (
      <div className="flex flex-col items-start justify-center py-6">
        <div className="text-[13px] text-muted">{spec.title ?? (col ? humanize(col) : "Value")}</div>
        <div className="mt-1 text-4xl font-semibold tracking-tight tabular-nums sm:text-5xl">
          {typeof v === "number" ? formatNumber(v) : formatCell(v ?? null)}
        </div>
      </div>
    );
  }

  const tooltip = (
    <Tooltip
      cursor={{ fill: palette.grid, opacity: 0.4 }}
      contentStyle={{ background: palette.surface, border: `1px solid ${palette.grid}`, borderRadius: 10, fontSize: 12, color: palette.text, boxShadow: "0 8px 24px -8px rgb(0 0 0 / .2)" }}
      labelStyle={{ color: palette.text, fontWeight: 500, marginBottom: 4 }}
      formatter={(v: number | string, name: string) => [typeof v === "number" ? formatNumber(v) : v, humanize(name)]}
      labelFormatter={(l: string | number) => fmtX(l)}
    />
  );
  const axisProps = { stroke: palette.axis, tick: { fill: palette.axis, fontSize: 11 }, tickLine: false, axisLine: false } as const;
  const monthly =
    xType === "date" && data.length > 1 && data.every((d) => /^\d{4}-\d{2}-01(?:[T ]00:00(?::00)?)?/.test(String(d[x] ?? "")));
  const fmtX = (v: string | number) =>
    monthly ? new Date(String(v).slice(0, 10) + "T00:00:00Z").toLocaleDateString(undefined, { month: "short", year: "numeric", timeZone: "UTC" }) : formatCell(v, xType);
  const xTick = (v: string | number) => {
    const s = fmtX(v);
    return s.length > 14 ? `${s.slice(0, 13)}…` : s;
  };

  if (spec.type === "pie" && data.length <= 8) {
    const y = ys[0];
    return (
      <ResponsiveContainer width="100%" height={300}>
        <PieChart>
          <Pie data={data} dataKey={y} nameKey={x} innerRadius="55%" outerRadius="85%" paddingAngle={2} stroke={palette.surface} strokeWidth={2}>
            {data.map((_, i) => (
              <PieCell key={i} fill={palette.series[i % palette.series.length]} />
            ))}
          </Pie>
          {tooltip}
          <Legend wrapperStyle={{ fontSize: 12, color: palette.axis }} formatter={(v: string) => fmtX(v)} />
        </PieChart>
      </ResponsiveContainer>
    );
  }

  if (spec.type === "line") {
    return (
      <ResponsiveContainer width="100%" height={300}>
        <LineChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
          <CartesianGrid vertical={false} stroke={palette.grid} />
          <XAxis dataKey={x} {...axisProps} tickFormatter={xTick} minTickGap={24} />
          <YAxis {...axisProps} width={56} tickFormatter={(v: number) => formatCompact(v)} />
          {tooltip}
          {ys.length > 1 && <Legend wrapperStyle={{ fontSize: 12 }} formatter={(v: string) => humanize(v)} />}
          {ys.map((y, i) => (
            <Line key={y} type="monotone" dataKey={y} stroke={palette.series[i % palette.series.length]} strokeWidth={2} dot={data.length <= 24} activeDot={{ r: 4 }} />
          ))}
        </LineChart>
      </ResponsiveContainer>
    );
  }

  // bar (also the fallback for pies with too many slices)
  const horizontal = data.length > 8 && data.every((d) => String(d[x] ?? "").length > 10);
  return (
    <ResponsiveContainer width="100%" height={horizontal ? Math.max(260, data.length * 28) : 300}>
      <BarChart data={data} layout={horizontal ? "vertical" : "horizontal"} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
        <CartesianGrid vertical={horizontal} horizontal={!horizontal} stroke={palette.grid} />
        {horizontal ? (
          <>
            <XAxis type="number" {...axisProps} tickFormatter={(v: number) => formatCompact(v)} />
            <YAxis type="category" dataKey={x} {...axisProps} width={140} tickFormatter={xTick} />
          </>
        ) : (
          <>
            <XAxis dataKey={x} {...axisProps} tickFormatter={xTick} interval="preserveStartEnd" minTickGap={8} />
            <YAxis {...axisProps} width={56} tickFormatter={(v: number) => formatCompact(v)} />
          </>
        )}
        {tooltip}
        {ys.length > 1 && <Legend wrapperStyle={{ fontSize: 12 }} formatter={(v: string) => humanize(v)} />}
        {ys.map((y, i) => (
          <Bar key={y} dataKey={y} fill={palette.series[i % palette.series.length]} radius={horizontal ? [0, 4, 4, 0] : [4, 4, 0, 0]} maxBarSize={48} />
        ))}
      </BarChart>
    </ResponsiveContainer>
  );
}
