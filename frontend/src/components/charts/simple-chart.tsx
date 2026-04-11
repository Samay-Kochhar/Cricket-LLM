import type { ChartBlock } from "@/lib/api-types";


type SimpleChartProps = {
  chart: ChartBlock;
};


export function SimpleChart({ chart }: SimpleChartProps) {
  const maxValue = Math.max(...chart.series.map((point) => point.value), 1);

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
