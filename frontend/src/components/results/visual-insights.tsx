"use client";

import { useMemo, useState, type CSSProperties, type ReactNode } from "react";

import type {
  FieldZoneMetric,
  PitchMapCell,
  QueryResponse,
  RadarMetric,
  ShotTypeMetric,
  VisualCoverage,
  WagonWheelPoint,
  WagonWheelSector,
} from "@/lib/api-types";

type VisualInsightsProps = {
  result: QueryResponse;
};

type PitchView = "all" | "strike_rate" | "wickets" | "fours" | "sixes" | "running";
type WagonView = "classic" | "summary";

const PITCH_LINE_ORDER = [
  "WIDE_OUTSIDE_OFFSTUMP",
  "OUTSIDE_OFFSTUMP",
  "ON_THE_STUMPS",
  "DOWN_LEG",
] as const;

const PITCH_LENGTH_ORDER = [
  "FULL_TOSS",
  "YORKER",
  "FULL",
  "GOOD_LENGTH",
  "SHORT_OF_A_GOOD_LENGTH",
  "SHORT",
] as const;

const LABEL_OVERRIDES: Record<string, string> = {
  LEG_GLANCE: "Leg glance",
  FLICK: "Flick",
  ON_DRIVE: "On drive",
  OFF_SIDE_DRIVE_ON_FRONT_FOOT: "Off-side drive",
  COVER_DRIVE: "Cover drive",
  PULL: "Pull",
  STEERED: "Steered",
  CUT_SHOT: "Cut shot",
  PULL_HOOK_ON_BACK_FOOT: "Pull / hook",
  ON_SIDE_DRIVE_ON_FRONT_FOOT: "On-side drive",
  WIDE_OUTSIDE_OFFSTUMP: "Wide outside off",
  OUTSIDE_OFFSTUMP: "Outside off",
  ON_THE_STUMPS: "On the stumps",
  DOWN_LEG: "Down leg",
  FULL_TOSS: "Full toss",
  GOOD_LENGTH: "Good length",
  SHORT_OF_A_GOOD_LENGTH: "Back of a length",
  YORKER: "Yorker",
};

const OUTCOME_PALETTE = {
  wicket: "#ef5350",
  six: "#ffd166",
  four: "#f28f3b",
  triple: "#67a3ff",
  double: "#48c9b0",
  single: "#7ce2b4",
  dot: "#c7d1d9",
} as const;

function beautifyLabel(value: string) {
  if (LABEL_OVERRIDES[value]) {
    return LABEL_OVERRIDES[value];
  }
  return value
    .replace(/_/g, " ")
    .toLowerCase()
    .replace(/\b\w/g, (match) => match.toUpperCase());
}

function formatPercent(value: number | null | undefined, digits = 1) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "-";
  }
  return `${value.toFixed(digits)}%`;
}

function sumRunning(cell: PitchMapCell | WagonWheelSector | FieldZoneMetric) {
  return cell.singles + cell.doubles + cell.triples;
}

function outcomeSwatch(outcome: keyof typeof OUTCOME_PALETTE) {
  return {
    backgroundColor: OUTCOME_PALETTE[outcome],
  };
}

function CoverageBadge({ coverage }: { coverage: VisualCoverage }) {
  return (
    <div className="coverage-badge">
      <strong>{coverage.coverage_percentage}% coverage</strong>
      <span>
        {coverage.covered_balls} / {coverage.total_balls} balls
      </span>
    </div>
  );
}

function ToggleVisualCard({
  eyebrow,
  title,
  coverage,
  controls,
  front,
  back,
  className,
}: {
  eyebrow: string;
  title: string;
  coverage?: VisualCoverage | null;
  controls?: ReactNode;
  front: ReactNode;
  back: ReactNode;
  className?: string;
}) {
  const [showMath, setShowMath] = useState(false);

  return (
    <article className={`panel visual-card ${className ?? ""}`}>
      <div className="visual-card-header">
        <div>
          <span className="eyebrow">{eyebrow}</span>
          <h3 className="visual-title">{title}</h3>
        </div>
        <div className="visual-card-actions">
          {controls}
          {coverage ? <CoverageBadge coverage={coverage} /> : null}
          <button className="ghost-button" onClick={() => setShowMath((current) => !current)} type="button">
            {showMath ? "Show chart" : "Show math"}
          </button>
        </div>
      </div>
      {showMath ? <div className="visual-card-backface">{back}</div> : front}
      {coverage ? <p className="muted-copy">{coverage.detail}</p> : null}
    </article>
  );
}

function MathList({
  title,
  items,
  note,
}: {
  title: string;
  items: string[];
  note?: string;
}) {
  return (
    <div className="math-panel">
      <h4 className="card-title">{title}</h4>
      <ul className="evidence-list">
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
      {note ? <p className="muted-copy">{note}</p> : null}
    </div>
  );
}

function getPitchCellValue(cell: PitchMapCell, view: PitchView) {
  if (view === "strike_rate") {
    return cell.strike_rate ?? 0;
  }
  if (view === "wickets") {
    return cell.wicket_balls;
  }
  if (view === "fours") {
    return cell.fours;
  }
  if (view === "sixes") {
    return cell.sixes;
  }
  if (view === "running") {
    return sumRunning(cell);
  }
  return cell.strike_rate ?? 0;
}

function pitchCellColor(cell: PitchMapCell, view: PitchView, maxValue: number) {
  const ratio = maxValue > 0 ? getPitchCellValue(cell, view) / maxValue : 0;
  const alpha = 0.18 + ratio * 0.52;
  if (view === "wickets") {
    return `rgba(239, 83, 80, ${alpha})`;
  }
  if (view === "sixes") {
    return `rgba(255, 209, 102, ${alpha})`;
  }
  if (view === "fours") {
    return `rgba(242, 143, 59, ${alpha})`;
  }
  if (view === "running") {
    return `rgba(72, 201, 176, ${alpha})`;
  }
  return `rgba(124, 226, 180, ${alpha})`;
}

function PitchMap({
  cells,
  view,
  handedness,
}: {
  cells: PitchMapCell[];
  view: PitchView;
  handedness?: string | null;
}) {
  const pitchLines = useMemo(
    () => handedness === "LHB" ? [...PITCH_LINE_ORDER].reverse() : [...PITCH_LINE_ORDER],
    [handedness],
  );
  const pitchGridStyle = {
    "--pitch-line-columns": handedness === "LHB" ? "1fr 0.6fr 0.5fr 0.5fr" : "0.5fr 0.5fr 0.6fr 1fr",
  } as CSSProperties;
  const cellMap = useMemo(
    () => new Map(cells.map((cell) => [`${cell.length}:${cell.line}`, cell])),
    [cells],
  );
  const maxValue = Math.max(
    ...cells
      .filter((cell) => PITCH_LINE_ORDER.includes(cell.line as (typeof PITCH_LINE_ORDER)[number]))
      .map((cell) => getPitchCellValue(cell, view)),
    1,
  );

  return (
    <div className="pitch-visual" style={pitchGridStyle}>
      <div className="pitch-line-headers">
        <span />
        {pitchLines.map((line) => (
          <span className="pitch-axis-label" key={line}>
            {beautifyLabel(line)}
          </span>
        ))}
      </div>

      <div className="pitch-board">
        <div className="pitch-grid">
          {PITCH_LENGTH_ORDER.map((length) => (
            <div className="pitch-grid-row" key={length}>
              <div className="pitch-length-label">{beautifyLabel(length)}</div>
              {pitchLines.map((line) => {
                const cell = cellMap.get(`${length}:${line}`);
                if (!cell) {
                  return (
                    <div className="pitch-grid-cell empty" key={`${length}:${line}`}>
                      <span>No deliveries</span>
                    </div>
                  );
                }
                return (
                  <div
                    className="pitch-grid-cell"
                    key={`${length}:${line}`}
                    style={{ backgroundColor: pitchCellColor(cell, view, maxValue) }}
                    title={`${beautifyLabel(length)} / ${beautifyLabel(line)}`}
                  >
                    <strong>{cell.strike_rate?.toFixed(1) ?? "-"}</strong>
                    <span>SR</span>
                    <div className="pitch-cell-stats">
                      <span className="mini-chip">1-3 {sumRunning(cell)}</span>
                      <span className="mini-chip four">4 {cell.fours}</span>
                      <span className="mini-chip six">6 {cell.sixes}</span>
                      <span className="mini-chip wicket">W {cell.wicket_balls}</span>
                    </div>
                  </div>
                );
              })}
              {length === "FULL_TOSS" ? (
                <div className="pitch-stumps batting" aria-hidden="true">
                  <span />
                  <span />
                  <span />
                </div>
              ) : null}
            </div>
          ))}
        </div>
      </div>

      <div className="outcome-legend">
        <span className="legend-item">
          <span className="legend-dot" style={outcomeSwatch("single")} />
          1-3 runs
        </span>
        <span className="legend-item">
          <span className="legend-dot" style={outcomeSwatch("four")} />
          Four
        </span>
        <span className="legend-item">
          <span className="legend-dot" style={outcomeSwatch("six")} />
          Six
        </span>
        <span className="legend-item">
          <span className="legend-dot" style={outcomeSwatch("wicket")} />
          Wicket
        </span>
      </div>
    </div>
  );
}

function normalizeWagonPoint(point: WagonWheelPoint) {
  return {
    x: 18 + (point.x / 389) * 264,
    y: 18 + (point.y / 381) * 264,
  };
}

function pointFromPolar(radius: number, angle: number) {
  return {
    x: 150 + Math.cos(angle) * radius,
    y: 150 + Math.sin(angle) * radius,
  };
}

function sectorArcPath(startAngle: number, endAngle: number, radius = 126, innerRadius = 54) {
  const outerStart = pointFromPolar(radius, startAngle);
  const outerEnd = pointFromPolar(radius, endAngle);
  const innerEnd = pointFromPolar(innerRadius, endAngle);
  const innerStart = pointFromPolar(innerRadius, startAngle);
  const largeArcFlag = endAngle - startAngle > Math.PI ? 1 : 0;
  return [
    `M ${innerStart.x} ${innerStart.y}`,
    `L ${outerStart.x} ${outerStart.y}`,
    `A ${radius} ${radius} 0 ${largeArcFlag} 1 ${outerEnd.x} ${outerEnd.y}`,
    `L ${innerEnd.x} ${innerEnd.y}`,
    `A ${innerRadius} ${innerRadius} 0 ${largeArcFlag} 0 ${innerStart.x} ${innerStart.y}`,
    "Z",
  ].join(" ");
}

function ClassicWagon({
  points,
  sectors,
}: {
  points: WagonWheelPoint[];
  sectors: WagonWheelSector[];
}) {
  const labels = sectors.length ? sectors : [];

  return (
    <div className="wagon-classic-wrap">
      <svg viewBox="0 0 300 300" aria-label="Classic wagon wheel" className="wagon-plot">
        <circle className="wagon-circle" cx="150" cy="150" r="126" />
        <circle className="wagon-circle inner" cx="150" cy="150" r="86" />
        <circle className="wagon-circle inner" cx="150" cy="150" r="54" />
        <circle className="wagon-origin" cx="150" cy="150" r="6" />
        {Array.from({ length: 8 }).map((_, index) => {
          const angle = -Math.PI / 2 + index * (Math.PI / 4);
          const end = pointFromPolar(126, angle);
          return <line className="wagon-axis" key={index} x1="150" x2={end.x} y1="150" y2={end.y} />;
        })}
        {points.map((point, index) => {
          const normalized = normalizeWagonPoint(point);
          return (
            <g key={`${point.x}-${point.y}-${index}`}>
              <line className="wagon-axis faint" x1="150" x2={normalized.x} y1="150" y2={normalized.y} />
              <circle
                className="wagon-hit"
                cx={normalized.x}
                cy={normalized.y}
                r="4"
                style={{ fill: OUTCOME_PALETTE[point.outcome] }}
              />
            </g>
          );
        })}
        {labels.map((sector, index) => {
          const angle = -Math.PI / 2 + index * (Math.PI / 4) + Math.PI / 8;
          const label = pointFromPolar(144, angle);
          return (
            <text className="wagon-sector-label" key={sector.zone_id} textAnchor="middle" x={label.x} y={label.y}>
              {beautifyLabel(sector.label)}
            </text>
          );
        })}
      </svg>
      <div className="outcome-legend">
        {(["single", "double", "triple", "four", "six", "wicket"] as const).map((outcome) => (
          <span className="legend-item" key={outcome}>
            <span className="legend-dot" style={outcomeSwatch(outcome)} />
            {outcome === "single" ? "1 run" : outcome === "double" ? "2 runs" : outcome === "triple" ? "3 runs" : outcome === "four" ? "Four" : outcome === "six" ? "Six" : "Wicket"}
          </span>
        ))}
      </div>
    </div>
  );
}

function SummaryWheel({ sectors }: { sectors: WagonWheelSector[] }) {
  return (
    <div className="wagon-summary-wheel">
      <svg viewBox="0 0 300 300" aria-label="Run share by field sector" className="wagon-plot">
        <circle className="wagon-circle" cx="150" cy="150" r="126" />
        <circle className="wagon-circle inner" cx="150" cy="150" r="54" />
        {sectors.map((sector, index) => {
          const startAngle = -Math.PI / 2 + index * (Math.PI / 4);
          const endAngle = startAngle + Math.PI / 4;
          const intensity = 0.18 + (sector.run_share_percentage / 100) * 0.58;
          const fill = `rgba(124, 226, 180, ${intensity})`;
          const labelPoint = pointFromPolar(94, startAngle + Math.PI / 8);
          return (
            <g key={sector.zone_id}>
              <path d={sectorArcPath(startAngle, endAngle)} style={{ fill }} className="wagon-sector-fill" />
              <text className="wagon-sector-label" textAnchor="middle" x={labelPoint.x} y={labelPoint.y - 10}>
                {beautifyLabel(sector.label)}
              </text>
              <text className="wagon-sector-label emphasis" textAnchor="middle" x={labelPoint.x} y={labelPoint.y + 8}>
                {sector.run_share_percentage.toFixed(1)}%
              </text>
            </g>
          );
        })}
      </svg>
      <div className="wagon-summary-metrics">
        {sectors.map((sector) => (
          <div className="wagon-summary-row" key={sector.zone_id}>
            <div>
              <strong>{beautifyLabel(sector.label)}</strong>
              <div className="field-zone-meta">
                SR {sector.strike_rate?.toFixed(1) ?? "-"} | W {sector.wicket_balls}
              </div>
            </div>
            <span className="chip">{sector.run_share_percentage.toFixed(1)}% runs</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function ShotTypeModule({ metrics }: { metrics: ShotTypeMetric[] }) {
  const productive = [...metrics].sort(
    (left, right) => (right.run_share_percentage ?? 0) - (left.run_share_percentage ?? 0),
  );
  const control = [...metrics].sort(
    (left, right) => (right.control_percentage ?? 0) - (left.control_percentage ?? 0),
  );

  return (
    <div className="split-bars shot-type-panels">
      <section className="editorial-card">
        <p className="chart-subtitle">Most productive shots</p>
        <div className="chart-list">
          {productive.map((metric) => (
            <div className="chart-row" key={`${metric.shot}-runs`}>
              <span className="chart-label">{beautifyLabel(metric.shot)}</span>
              <div className="chart-bar-track">
                <div
                  className="chart-bar-fill warm"
                  style={{ width: `${metric.run_share_percentage ?? 0}%` }}
                />
              </div>
              <span className="chart-value">{formatPercent(metric.run_share_percentage)}</span>
            </div>
          ))}
        </div>
      </section>

      <section className="editorial-card">
        <p className="chart-subtitle">Control percentage</p>
        <div className="chart-list">
          {control.map((metric) => (
            <div className="chart-row" key={`${metric.shot}-control`}>
              <span className="chart-label">{beautifyLabel(metric.shot)}</span>
              <div className="chart-bar-track">
                <div
                  className="chart-bar-fill cool"
                  style={{ width: `${metric.control_percentage ?? 0}%` }}
                />
              </div>
              <span className="chart-value">{formatPercent(metric.control_percentage)}</span>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}

function FieldZoneMap({ zones }: { zones: FieldZoneMetric[] }) {
  return (
    <div className="field-zone-grid enhanced">
      {zones.map((zone) => (
        <article className="field-zone-card" key={zone.zone_id}>
          <span className="field-zone-label">{beautifyLabel(zone.label)}</span>
          <strong>{zone.run_share_percentage.toFixed(1)}% of runs</strong>
          <span className="field-zone-meta">
            SR {zone.strike_rate?.toFixed(1) ?? "-"} | W {zone.wicket_balls}
          </span>
          <span className="field-zone-meta">
            1s {zone.singles} | 2s {zone.doubles} | 3s {zone.triples} | 4s {zone.fours} | 6s {zone.sixes}
          </span>
        </article>
      ))}
    </div>
  );
}

function RadarChart({
  points,
  subjectLabel,
  benchmarkLabel,
}: {
  points: RadarMetric[];
  subjectLabel: string;
  benchmarkLabel: string;
}) {
  const center = 120;
  const radius = 72;
  const scaleMax = Math.max(
    ...points.flatMap((point) => [point.subject, point.benchmark]),
    100,
  );

  function pointToPosition(index: number, value: number) {
    const angle = -Math.PI / 2 + (index / points.length) * Math.PI * 2;
    const scaled = (value / scaleMax) * radius;
    return {
      x: center + Math.cos(angle) * scaled,
      y: center + Math.sin(angle) * scaled,
    };
  }

  const subjectPath = points
    .map((point, index) => pointToPosition(index, point.subject))
    .map(({ x, y }) => `${x},${y}`)
    .join(" ");

  const benchmarkPath = points
    .map((point, index) => pointToPosition(index, point.benchmark))
    .map(({ x, y }) => `${x},${y}`)
    .join(" ");

  return (
    <div className="radar-panel">
      <svg viewBox="0 0 240 240" aria-label="Radar comparison chart" className="radar-plot">
        {[22, 40, 56, 72].map((ring) => (
          <circle className="radar-ring" cx={center} cy={center} key={ring} r={ring} />
        ))}
        {points.map((point, index) => {
          const angle = -Math.PI / 2 + (index / points.length) * Math.PI * 2;
          const labelX = center + Math.cos(angle) * 92;
          const labelY = center + Math.sin(angle) * 92;
          const textAnchor =
            Math.cos(angle) > 0.25 ? "start" : Math.cos(angle) < -0.25 ? "end" : "middle";
          return (
            <g key={point.label}>
              <line
                className="radar-axis"
                x1={center}
                x2={center + Math.cos(angle) * radius}
                y1={center}
                y2={center + Math.sin(angle) * radius}
              />
              <text className="radar-label" textAnchor={textAnchor} x={labelX} y={labelY}>
                {point.label}
              </text>
            </g>
          );
        })}
        <polygon className="radar-shape benchmark" points={benchmarkPath} />
        <polygon className="radar-shape subject" points={subjectPath} />
      </svg>
      <div className="radar-legend">
        <span className="legend-pill boundary">{subjectLabel}</span>
        <span className="legend-pill control">{benchmarkLabel}</span>
      </div>
    </div>
  );
}

export function VisualInsights({ result }: VisualInsightsProps) {
  const [pitchView, setPitchView] = useState<PitchView>("all");
  const [wagonMode, setWagonMode] = useState<WagonView>("classic");
  const visuals = result.visuals;
  const hasVisuals = useMemo(
    () =>
      Boolean(
        visuals?.pitch_map ||
          visuals?.wagon_wheel ||
          visuals?.shot_profile ||
          visuals?.field_zones ||
          visuals?.radar,
      ),
    [visuals],
  );

  if (!hasVisuals) {
    return (
      <section className="panel visual-card">
        <div className="visual-card-header">
          <div>
            <span className="eyebrow">Visual workspace</span>
            <h3 className="visual-title">No backend visual payload for this query</h3>
          </div>
        </div>
        <p className="muted-copy">
          This response class does not currently return a pitch map, wagon wheel, shot profile, or
          field-zone bundle.
        </p>
      </section>
    );
  }

  return (
    <section className="visual-suite">
      {visuals?.pitch_map ? (
        <ToggleVisualCard
          className="visual-card-pitch"
          coverage={visuals.pitch_map.coverage}
          eyebrow="Pitch map"
          title="Line, length, strike rate, and wicket pressure"
          controls={
            <div className="segmented-control">
              {([
                ["all", "All"],
                ["strike_rate", "SR"],
                ["wickets", "W"],
                ["fours", "4s"],
                ["sixes", "6s"],
                ["running", "1-3"],
              ] as const).map(([value, label]) => (
                <button
                  className={pitchView === value ? "segmented-button is-active" : "segmented-button"}
                  key={value}
                  onClick={() => setPitchView(value)}
                  type="button"
                >
                  {label}
                </button>
              ))}
            </div>
          }
          front={
            <PitchMap
              cells={visuals.pitch_map.cells}
              handedness={visuals.pitch_map.handedness}
              view={pitchView}
            />
          }
          back={
            <MathList
              title="How this pitch map is calculated"
              items={[
                "Each tile is one recorded line/length bucket from the ODI feed, not a true tracked Hawk-Eye bounce coordinate.",
                "Strike rate in a tile = runs from that tile / balls in that tile * 100.",
                "Wickets = deliveries in that tile where out = true.",
                "1-3 runs combines singles, doubles, and triples to separate running value from boundary value.",
                "The default view shows strike rate in every tile plus the event counts for 1-3 runs, 4s, 6s, and wickets.",
              ]}
              note="The dataset contains Yorker, Full toss, Full, Good length, Short of a good length, and Short. We label 'Short of a good length' as 'Back of a length' in the UI."
            />
          }
        />
      ) : null}

      {visuals?.wagon_wheel ? (
        <ToggleVisualCard
          coverage={visuals.wagon_wheel.coverage}
          eyebrow="Wagon wheel"
          title="Classic event map and sector summary"
          controls={
            <div className="segmented-control">
              <button
                className={wagonMode === "classic" ? "segmented-button is-active" : "segmented-button"}
                onClick={() => setWagonMode("classic")}
                type="button"
              >
                Classic
              </button>
              <button
                className={wagonMode === "summary" ? "segmented-button is-active" : "segmented-button"}
                onClick={() => setWagonMode("summary")}
                type="button"
              >
                Summary wheel
              </button>
            </div>
          }
          front={
            wagonMode === "classic" ? (
              <ClassicWagon points={visuals.wagon_wheel.points} sectors={visuals.wagon_wheel.sectors} />
            ) : (
              <SummaryWheel sectors={visuals.wagon_wheel.sectors} />
            )
          }
          back={
            <MathList
              title="How the wagon wheel is calculated"
              items={[
                "Classic view plots recorded wagonX and wagonY field coordinates from the ODI feed.",
                "Each point is colored by the delivery outcome: 1, 2, 3, 4, 6, or wicket.",
                "Summary wheel groups deliveries by wagonZone sector and shows run share, strike rate, and wickets for each sector.",
                "Run share in a sector = sector runs / total runs across all scored sectors * 100.",
                "Sector strike rate = sector runs / sector balls * 100.",
              ]}
              note="The ODI feed uses wagonZone 1-8. Handedness is used to map those sectors into readable field labels."
            />
          }
        />
      ) : null}

      {visuals?.shot_profile ? (
        <ToggleVisualCard
          className="visual-card-shot"
          coverage={visuals.shot_profile.coverage}
          eyebrow="Shot type profile"
          title="Run share and control by recorded shot"
          front={<ShotTypeModule metrics={visuals.shot_profile.metrics} />}
          back={
            <MathList
              title="How the shot profile is calculated"
              items={[
                "Run share = runs from a shot / total runs across the displayed shot types * 100.",
                "Control % comes from the dataset's binary control field averaged within each shot type.",
                "False-shot % = 100 - control %.",
                "Dismissal rate = dismissals on that shot / balls for that shot * 100.",
              ]}
              note="Coverage is below 100% whenever the ODI feed has missing shot labels or records a delivery as NO_SHOT."
            />
          }
        />
      ) : null}

      {visuals?.field_zones ? (
        <ToggleVisualCard
          coverage={visuals.field_zones.coverage}
          eyebrow="Field zones"
          title="Run share, strike rate, and wickets by sector"
          front={<FieldZoneMap zones={visuals.field_zones.zones} />}
          back={
            <MathList
              title="How the field-zone map is calculated"
              items={[
                "Field zones come from the ODI feed's wagonZone sector value, not from freehand geometric inference.",
                "Run share = runs in the zone / total zone runs * 100.",
                "Strike rate = runs in the zone / balls in the zone * 100.",
                "Wicket count = wicket events recorded inside that zone.",
              ]}
              note="Coverage drops below 100% when wagonZone is blank or recorded as 0. Those deliveries cannot be placed into a named field sector."
            />
          }
        />
      ) : null}

      {visuals?.radar ? (
        <ToggleVisualCard
          className="visual-card-radar"
          coverage={null}
          eyebrow="H2H radar"
          title="Subject versus benchmark"
          front={
            <div className="radar-layout">
              <RadarChart
                benchmarkLabel={visuals.radar.benchmark_label}
                points={visuals.radar.metrics}
                subjectLabel={visuals.radar.subject_label}
              />
              <div className="radar-metrics">
                {visuals.radar.metrics.map((metric) => (
                  <div className="radar-metric-row" key={metric.label}>
                    <span>{metric.label}</span>
                    <strong>
                      {metric.subject} / {metric.benchmark}
                    </strong>
                  </div>
                ))}
              </div>
            </div>
          }
          back={
            <MathList
              title="How the radar is calculated"
              items={[
                "Each spoke compares the subject against either another player or the ODI baseline.",
                "ODI baseline means the aggregate batting benchmark from the whole ODI dataset for the same filter context. If the view is filtered to death overs, the baseline is all death-over balls in the dataset. If there is no phase filter, it is the full ODI dataset benchmark.",
                "Strike Rate = runs / balls * 100.",
                "Boundary % = balls that scored 4 or 6 / balls * 100.",
                "Control % = average of the dataset control field for the same sample.",
                "Dismissal Resistance = 100 - (dismissals / balls * 100). Higher is better because it means fewer dismissals per ball.",
                "Vs Pace SR and Vs Spin SR are strike rates calculated only against bowl_kind = pace bowler and bowl_kind = spin bowler.",
              ]}
              note="The radar is a compact benchmark view, not a role-adjusted model. ODI baseline here is a filtered dataset aggregate, not a prediction or percentile score."
            />
          }
        />
      ) : null}
    </section>
  );
}
