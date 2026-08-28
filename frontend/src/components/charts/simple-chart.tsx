import type { ChartBlock } from "@/lib/api-types";


type SimpleChartProps = {
  chart: ChartBlock;
};


function niceStep(range: number, targetIntervals = 4) {
  const roughStep = Math.max(range / targetIntervals, Number.EPSILON);
  const magnitude = 10 ** Math.floor(Math.log10(roughStep));
  const normalized = roughStep / magnitude;
  const factor = [1, 2, 2.5, 5, 10].find((candidate) => candidate >= normalized) ?? 10;
  return factor * magnitude;
}


function formatAxisValue(value: number, step: number) {
  const decimals = Math.max(0, Math.ceil(-Math.log10(step)));
  return value.toFixed(Math.min(decimals, 2));
}


export function SimpleChart({ chart }: SimpleChartProps) {
  const maxValue = Math.max(...chart.series.map((point) => point.value), 1);

  if (chart.chart_type === "line" && chart.series.length > 0) {
    const values = chart.series.map((point) => point.value);
    const minValue = Math.min(...values);
    const maxLineValue = Math.max(...values);
    const rawRange = maxLineValue - minValue;
    const fallbackPadding = Math.max(Math.abs(maxLineValue) * 0.1, 1);
    const step = niceStep(rawRange || fallbackPadding * 2);
    let axisMin = Math.floor(minValue / step) * step;
    let axisMax = Math.ceil(maxLineValue / step) * step;

    if (minValue - axisMin < step * 0.25) {
      axisMin -= step;
    }
    if (axisMax - maxLineValue < step * 0.25) {
      axisMax += step;
    }
    if (minValue >= 0) {
      axisMin = Math.max(0, axisMin);
    }
    if (axisMax === axisMin) {
      axisMax = axisMin + step;
    }

    const valueRange = axisMax - axisMin;
    const intervalCount = Math.round(valueRange / step);
    const ticks = Array.from({ length: intervalCount + 1 }, (_, index) => axisMin + index * step);
    const left = 56;
    const right = 570;
    const top = 24;
    const bottom = 176;
    const points = chart.series.map((point, index) => ({
      ...point,
      x: chart.series.length === 1
        ? (left + right) / 2
        : left + (index / (chart.series.length - 1)) * (right - left),
      y: bottom - ((point.value - axisMin) / valueRange) * (bottom - top),
    }));

    return (
      <div className="chart-card">
        <h3 className="card-title">{chart.title}</h3>
        <svg
          aria-label={`${chart.title} line chart`}
          className="simple-line-chart"
          role="img"
          viewBox="0 0 600 220"
        >
          {ticks.map((tick) => {
            const y = bottom - ((tick - axisMin) / valueRange) * (bottom - top);
            return (
              <g key={`${chart.title}-tick-${tick}`}>
                <line className="simple-line-grid" x1={left} x2={right} y1={y} y2={y} />
                <text className="simple-line-y-label" textAnchor="end" x={left - 10} y={y + 4}>
                  {formatAxisValue(tick, step)}
                </text>
              </g>
            );
          })}
          <line className="simple-line-axis" x1={left} x2={left} y1={top} y2={bottom} />
          <line className="simple-line-axis simple-line-x-axis" x1={left} x2={right} y1={bottom} y2={bottom} />
          <polyline
            className="simple-line-path"
            points={points.map((point) => `${point.x},${point.y}`).join(" ")}
          />
          {points.map((point) => (
            <g key={`${chart.title}-${point.label}`}>
              <circle className="simple-line-point" cx={point.x} cy={point.y} r="5">
                <title>{`${point.label}: ${point.value}`}</title>
              </circle>
              <text className="simple-line-value" textAnchor="middle" x={point.x} y={point.y - 10}>
                {point.value}
              </text>
              <text className="simple-line-label" textAnchor="middle" x={point.x} y={bottom + 24}>
                {point.label}
              </text>
            </g>
          ))}
        </svg>
      </div>
    );
  }

  return (
    <div className="chart-card">
      <h3 className="card-title">{chart.title}</h3>
      <div className="chart-list">
        {chart.series.map((point) => {
          const width = `${Math.max((point.value / maxValue) * 100, 4)}%`;
          return (
            <div className="chart-row" key={`${chart.title}-${point.label}`}>
              <div className="chart-label">{point.label}</div>
              <div className="chart-bar-track">
                <div className="chart-bar-fill" style={{ width }} />
              </div>
              <div className="chart-value">{point.value}</div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
