import { useEffect, useState } from "react";

const VARS = ["--chart-1", "--chart-2", "--chart-3", "--chart-4", "--chart-5", "--chart-6"];

export interface ChartTheme {
  series: string[];
  grid: string;
  axis: string;
  surface: string;
  text: string;
}

function read(): ChartTheme {
  const cs = getComputedStyle(document.documentElement);
  const rgb = (v: string, a = 1) => `rgb(${cs.getPropertyValue(v).trim().split(/\s+/).join(" ")} / ${a})`;
  return {
    series: VARS.map((v) => rgb(v)),
    grid: rgb("--border", 0.7),
    axis: rgb("--text-muted"),
    surface: rgb("--surface"),
    text: rgb("--text"),
  };
}

/** SVG attributes can't use CSS variables, so resolve them and re-read on theme change. */
export function useChartPalette(): ChartTheme {
  const [theme, setTheme] = useState<ChartTheme>(read);
  useEffect(() => {
    const obs = new MutationObserver(() => setTheme(read()));
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => obs.disconnect();
  }, []);
  return theme;
}
