import type { AnalyticsData } from '../api/client';

export function BarChartCard({
  title,
  subtitle,
  data,
  accent = 'var(--accent)',
  emptyText = 'No recorded data yet',
}: {
  title: string;
  subtitle?: string;
  data: { label: string; value: number }[];
  accent?: string;
  emptyText?: string;
}) {
  const max = Math.max(1, ...data.map((d) => d.value));

  return (
    <section className="card chart-card" aria-label={title}>
      <div className="card-header">
        <div>
          <h3>{title}</h3>
          {subtitle && <p className="muted small">{subtitle}</p>}
        </div>
      </div>
      {data.length === 0 || data.every((d) => d.value === 0) ? (
        <div className="empty-chart">{emptyText}</div>
      ) : (
        <div className="bar-chart" role="img" aria-label={title}>
          {data.map((item) => {
            const pct = Math.max(4, Math.round((item.value / max) * 100));
            return (
              <div key={item.label} className="bar-row">
                <span className="bar-label" title={item.label}>
                  {item.label}
                </span>
                <div className="bar-track">
                  <div className="bar-fill" style={{ width: `${pct}%`, background: accent }} />
                </div>
                <span className="bar-value">{item.value}</span>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}

export function VerticalColumnChartCard({
  title,
  subtitle,
  data,
  accent = 'var(--accent)',
  emptyText = 'No recorded data yet',
}: {
  title: string;
  subtitle?: string;
  data: { label: string; value: number }[];
  accent?: string;
  emptyText?: string;
}) {
  const max = Math.max(1, ...data.map((d) => d.value));

  return (
    <section className="card chart-card" aria-label={title}>
      <div className="card-header">
        <div>
          <h3>{title}</h3>
          {subtitle && <p className="muted small">{subtitle}</p>}
        </div>
      </div>
      {data.length === 0 ? (
        <div className="empty-chart">{emptyText}</div>
      ) : (
        <div className="column-chart" role="img" aria-label={title}>
          {data.map((item) => {
            const heightPct = Math.max(8, Math.round((item.value / max) * 100));
            return (
              <div key={item.label} className="column-item">
                <span className="column-val">{item.value}</span>
                <div className="column-track">
                  <div className="column-bar" style={{ height: `${heightPct}%`, background: accent }} />
                </div>
                <span className="column-label" title={item.label}>
                  {item.label}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}

export function FunnelChartCard({ conversion }: { conversion: AnalyticsData['interview_conversion'] }) {
  const stages = [
    { label: 'Matched', value: conversion.matched, color: 'var(--accent)' },
    { label: 'Prepared', value: conversion.prepared, color: 'var(--info)' },
    { label: 'Submitted', value: conversion.submitted, color: 'var(--success)' },
    { label: 'Interviews', value: conversion.interviews, color: 'var(--warning)' },
  ];
  const max = Math.max(1, ...stages.map((s) => s.value));

  return (
    <section className="card chart-card" aria-label="Interview conversion">
      <div className="card-header">
        <div>
          <h3>Interview conversion</h3>
          <p className="muted small">Submission-to-interview rate: {conversion.conversion_rate_pct}%</p>
        </div>
      </div>
      <div className="bar-chart">
        {stages.map((stage) => (
          <div key={stage.label} className="bar-row">
            <span className="bar-label">{stage.label}</span>
            <div className="bar-track">
              <div
                className="bar-fill"
                style={{ width: `${stage.value ? Math.max(8, Math.round((stage.value / max) * 100)) : 0}%`, background: stage.color }}
              />
            </div>
            <span className="bar-value">{stage.value}</span>
          </div>
        ))}
      </div>
    </section>
  );
}

export function SourcePerformanceCard({ sources }: { sources: AnalyticsData['source_performance'] }) {
  return (
    <section className="card chart-card" aria-label="Source performance">
      <div className="card-header">
        <div>
          <h3>Source performance</h3>
          <p className="muted small">Discovery volume, strong matches, and submissions per source</p>
        </div>
      </div>
      {sources.length === 0 ? (
        <div className="empty-chart">No job sources configured</div>
      ) : (
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>Source</th>
                <th>Reliability</th>
                <th>Opportunities</th>
                <th>Strong Matches</th>
                <th>Submitted</th>
              </tr>
            </thead>
            <tbody>
              {sources.map((s) => (
                <tr key={s.source_id}>
                  <td><strong>{s.name}</strong></td>
                  <td>{s.reliability_score}%</td>
                  <td>{s.opportunities}</td>
                  <td>{s.strong_matches}</td>
                  <td>{s.submitted}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
