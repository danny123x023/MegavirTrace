// A small line of real values for a case card, with the event marked.  Decorative detail: the
// card states the finding in words, so the chart only needs a short label.

type Props = {
  values: (number | null)[];
  highlight?: number[];
  width?: number;
  height?: number;
  label: string;
};

export default function Sparkline({ values, highlight = [], width = 132, height = 46, label }: Props) {
  const finite = values.filter((v): v is number => v !== null && Number.isFinite(v));
  if (finite.length < 2) return null;
  const min = Math.min(...finite), max = Math.max(...finite);
  const n = values.length;
  const X = (i: number) => 4 + (i / Math.max(1, n - 1)) * (width - 8);
  const Y = (v: number) => height - 5 - ((v - min) / (max - min || 1)) * (height - 10);
  let d = "";
  let pen = false;
  values.forEach((v, i) => {
    if (v === null || !Number.isFinite(v)) { pen = false; return; }
    d += `${pen ? "L" : "M"}${X(i).toFixed(1)},${Y(v).toFixed(1)}`;
    pen = true;
  });
  return (
    <svg className="sparkline" width={width} height={height} viewBox={`0 0 ${width} ${height}`} role="img" aria-label={label}>
      <path d={d} fill="none" stroke="var(--series-1)" strokeWidth={1.6} strokeLinejoin="round" strokeLinecap="round" />
      {highlight.map((i) => values[i] !== null && values[i] !== undefined && (
        <circle key={i} cx={X(i)} cy={Y(values[i] as number)} r={3.6} fill="var(--series-2)" stroke="var(--surface-1)" strokeWidth={1.5} />
      ))}
    </svg>
  );
}
