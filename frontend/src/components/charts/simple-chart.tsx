import type { ChartBlock } from "@/lib/api-types";


type SimpleChartProps = {
  chart: ChartBlock;
};


export function SimpleChart({ chart }: SimpleChartProps) {
  const maxValue = Math.max(...chart.series.map((point) => point.value), 1);

  if (chart.chart_type === "line" && chart.series.length > 0) {
    const values = chart.series.map((point) => point.value);
    const minValue = Math.min(...values);
    const lineMaxValue = Math.max(...values);
    const valueRange = lineMaxValue - minValue || 1;
    const left = 36;
    const right = 564;
    const top = 24;
    const bottom = 176;
    const points = chart.series.map((point, index) => ({
      ...point,
      x: chart.series.length === 1
        ? (left + right) / 2
        : left + (index / (chart.series.length - 1)) * (right - left),
      y: bottom - ((point.value - minValue) / valueRange) * (bottom - top),
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
          <line className="simple-line-axis" x1={left} x2={right} y1={bottom} y2={bottom} />
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
