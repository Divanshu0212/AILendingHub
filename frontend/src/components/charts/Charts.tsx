"use client";

/**
 * The chart primitives. Hand-drawn SVG, no charting library.
 *
 * A charting dependency would be the first runtime package in this frontend,
 * and these are four chart types over data whose shape the gateway fixes. SVG
 * with an explicit scale is less code than configuring a library, and it keeps
 * the arithmetic where a reviewer can see it.
 *
 * WHERE THE ARITHMETIC LIVES, AND WHY IT IS ALLOWED HERE
 * -------------------------------------------------------
 * Phase 7 §8 forbids the render layer computing a money figure, and the
 * no-client-math gate enforces it. Plotting is different in kind: mapping a
 * value the backend computed onto a pixel coordinate produces no new fact about
 * a customer, and it cannot — a bar's height is not a number anybody reads off
 * the screen. Every LABEL on these charts renders a value the backend sent,
 * never one derived here.
 *
 * That distinction is why this directory — and only this directory — is exempt
 * in BOTH gates that enforce the rule: the `no-restricted-syntax` override in
 * `.eslintrc.json`, and `PLOT_SURFACES` in `scripts/check-no-client-math.mjs`.
 * Scaling is confined here, and every other component still cannot multiply.
 *
 * If you are adding a file to this directory, the test is whether its output
 * is a coordinate or a claim. A pixel position is a coordinate. A percentage
 * a user reads is a claim, and belongs in the gateway payload.
 */

import type { ReactNode } from "react";

/** Chart ink, taken from the theme so both themes read correctly. */
const AXIS = "#94a3b8";
const GRID = "#e2e8f0";
const LABEL = "#64748b";

const SERIES = ["#0d4a85", "#2166a3", "#4a83bd", "#7ba7d3"];

function Frame({
  title,
  caption,
  children,
}: {
  readonly title: string;
  readonly caption?: string;
  readonly children: ReactNode;
}) {
  return (
    <figure className="m-0">
      <figcaption className="mb-2">
        <span className="text-sm font-semibold text-neutral-900">{title}</span>
        {caption !== undefined ? (
          <span className="ml-2 text-xs text-neutral-500">{caption}</span>
        ) : null}
      </figcaption>
      {children}
    </figure>
  );
}

// ---------------------------------------------------------------- line chart

export interface LineSeries {
  readonly name: string;
  readonly points: readonly { x: number; y: number }[];
}

/**
 * Multi-series line chart, for vintage curves.
 *
 * The y scale is fixed to the data's own maximum rather than to 1.0: a
 * cumulative bad rate of 4% plotted against a 0–100% axis is a flat line, and a
 * flat line says "nothing happened" when the truth is "the axis is wrong".
 */
export function LineChart({
  series,
  title,
  caption,
  xLabel,
  yLabel,
  formatY,
}: {
  readonly series: readonly LineSeries[];
  readonly title: string;
  readonly caption?: string;
  readonly xLabel: string;
  readonly yLabel: string;
  /** How an axis tick renders. Defaults to a percentage, which is what every
   *  rate series on these dashboards is. Lives here rather than at the call
   *  site because a tick is chart furniture, not a figure a page states. */
  readonly formatY?: (v: number) => string;
}) {
  const tick = formatY ?? ((v: number) => `${(v * 100).toFixed(1)}%`);
  const W = 560;
  const H = 240;
  const padL = 52;
  const padR = 14;
  const padT = 12;
  const padB = 34;

  const all = series.flatMap((s) => s.points);
  if (all.length === 0) return null;

  const xMax = Math.max(...all.map((p) => p.x));
  const yMax = Math.max(...all.map((p) => p.y)) || 1;

  const px = (x: number) => padL + (x / xMax) * (W - padL - padR);
  const py = (y: number) => H - padB - (y / yMax) * (H - padT - padB);

  const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => yMax * f);

  return (
    <Frame title={title} caption={caption}>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="w-full"
        role="img"
        aria-label={`${title}. ${yLabel} against ${xLabel}.`}
      >
        {ticks.map((t) => (
          <g key={t}>
            <line x1={padL} y1={py(t)} x2={W - padR} y2={py(t)} stroke={GRID} strokeWidth="1" />
            <text x={padL - 8} y={py(t) + 4} textAnchor="end" fontSize="10" fill={LABEL}>
              {tick(t)}
            </text>
          </g>
        ))}
        <line x1={padL} y1={H - padB} x2={W - padR} y2={H - padB} stroke={AXIS} strokeWidth="1" />

        {series.map((s, i) => (
          <polyline
            key={s.name}
            fill="none"
            stroke={SERIES[i % SERIES.length]}
            strokeWidth="2"
            strokeLinejoin="round"
            points={s.points.map((p) => `${px(p.x)},${py(p.y)}`).join(" ")}
          />
        ))}

        <text x={W - padR} y={H - 6} textAnchor="end" fontSize="10" fill={LABEL}>
          {xLabel}
        </text>
      </svg>

      <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1">
        {series.map((s, i) => (
          <li key={s.name} className="flex items-center gap-1.5 text-xs text-neutral-600">
            <span
              className="inline-block h-2 w-2 rounded-full"
              style={{ background: SERIES[i % SERIES.length] }}
            />
            {s.name}
          </li>
        ))}
      </ul>
    </Frame>
  );
}

// ----------------------------------------------------------------- bar chart

export interface Bar {
  readonly label: string;
  readonly value: number;
  readonly display: string;
  readonly sub?: string;
  readonly highlight?: boolean;
}

export function BarChart({
  bars,
  title,
  caption,
}: {
  readonly bars: readonly Bar[];
  readonly title: string;
  readonly caption?: string;
}) {
  const W = 560;
  const H = 220;
  const padT = 26;
  const padB = 42;
  const max = Math.max(...bars.map((b) => b.value)) || 1;
  const slot = W / bars.length;
  const barW = slot * 0.5;

  return (
    <Frame title={title} caption={caption}>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label={title}>
        <line x1={0} y1={H - padB} x2={W} y2={H - padB} stroke={AXIS} strokeWidth="1" />
        {bars.map((b, i) => {
          const h = (b.value / max) * (H - padT - padB);
          const x = slot * i + (slot - barW) / 2;
          const y = H - padB - h;
          return (
            <g key={b.label}>
              <rect
                x={x}
                y={y}
                width={barW}
                height={h}
                fill={b.highlight ? "#b54708" : "#0d4a85"}
                rx="2"
              />
              <text
                x={x + barW / 2}
                y={y - 7}
                textAnchor="middle"
                fontSize="12"
                fontWeight="600"
                fill="#0a3a68"
              >
                {b.display}
              </text>
              <text
                x={x + barW / 2}
                y={H - padB + 15}
                textAnchor="middle"
                fontSize="11"
                fill={LABEL}
              >
                {b.label}
              </text>
              {b.sub !== undefined ? (
                <text
                  x={x + barW / 2}
                  y={H - padB + 30}
                  textAnchor="middle"
                  fontSize="10"
                  fill={AXIS}
                >
                  {b.sub}
                </text>
              ) : null}
            </g>
          );
        })}
      </svg>
    </Frame>
  );
}

// -------------------------------------------------------------- heat matrix

export interface MatrixRow {
  readonly from: string;
  readonly total: number;
  readonly to: readonly { bucket: string; count: number; rate: number }[];
}

/**
 * The roll-rate matrix, shaded by transition rate.
 *
 * Shaded rather than plotted: the reader's question is "where do accounts in
 * this state go next", which is a row-wise comparison, and colour carries that
 * faster than seven small bar charts would.
 */
export function RollRateMatrix({
  buckets,
  rows,
  title,
  caption,
}: {
  readonly buckets: readonly string[];
  readonly rows: readonly MatrixRow[];
  readonly title: string;
  readonly caption?: string;
}) {
  return (
    <Frame title={title} caption={caption}>
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-xs">
          <thead>
            <tr>
              <th className="p-1.5 text-left font-medium text-neutral-500">from \ to</th>
              {buckets.map((b) => (
                <th key={b} className="p-1.5 text-center font-medium text-neutral-500">
                  {b}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.from}>
                <th className="p-1.5 text-left font-medium text-neutral-800">{r.from}</th>
                {r.to.map((cell) => (
                  <td
                    key={cell.bucket}
                    className="p-1.5 text-center tabular-nums"
                    style={{
                      background:
                        cell.rate > 0 ? `rgba(13, 74, 133, ${0.08 + cell.rate * 0.72})` : undefined,
                      color: cell.rate > 0.55 ? "#fff" : "#334155",
                    }}
                    title={`${cell.count.toLocaleString()} of ${r.total.toLocaleString()}`}
                  >
                    {cell.rate > 0.001 ? `${(cell.rate * 100).toFixed(0)}%` : "·"}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Frame>
  );
}

// ----------------------------------------------------------- provenance tag

export function ProvenanceTag({
  provenance,
}: {
  readonly provenance: {
    readonly track: string;
    readonly dataset: string;
    readonly isGateEvidence: boolean;
  };
}) {
  return (
    <p className="mt-3 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-neutral-500">
      <span className="rounded bg-emerald-50 px-1.5 py-0.5 font-mono text-fresh-ok">
        Track {provenance.track}
      </span>
      <span className="font-mono">{provenance.dataset}</span>
      <span className="text-neutral-400">
        · real data, not this bank&apos;s book · not gate evidence
      </span>
    </p>
  );
}
