import { useEffect, useState } from 'react';
import {
  Activity,
  Award,
  Briefcase,
  CalendarCheck,
  CheckCircle2,
  Clock,
  Pause,
  Play,
  Search,
  Sparkles,
  XCircle,
} from 'lucide-react';
import { api, type AnalyticsData, type BotStatusData, type OverviewData } from '../api/client';
import { BarChartCard, FunnelChartCard, SourcePerformanceCard, VerticalColumnChartCard } from './Charts';

export function OverviewPage({
  onNavigate,
  onNotify,
}: {
  onNavigate: (page: string) => void;
  onNotify: (msg: string, isError?: boolean) => void;
}) {
  const [data, setData] = useState<OverviewData | null>(null);
  const [botStatus, setBotStatus] = useState<BotStatusData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    Promise.all([api.getOverview(), api.getBotStatus().catch(() => null)])
      .then(([res, bot]) => {
        if (active) {
          setData(res);
          setBotStatus(bot);
        }
      })
      .catch((err) => onNotify(err instanceof Error ? err.message : 'Failed to load overview', true))
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [onNotify]);

  if (loading) return <div className="card empty-state">Loading overview metrics...</div>;
  if (!data) return <div className="card empty-state">Unable to load overview data.</div>;

  const kpis = [
    { label: 'Total Opportunities Discovered', value: data.total_opportunities, icon: Briefcase, page: 'all-opportunities', tone: 'accent' },
    { label: 'New Opportunities (7d)', value: data.new_opportunities, icon: Sparkles, page: 'discovery', tone: 'info' },
    { label: 'Strong Matches (85+)', value: data.strong_matches, icon: Award, page: 'recommended', tone: 'success' },
    { label: 'Pending Approvals', value: data.pending_approvals, icon: Clock, page: 'approvals', tone: 'warning' },
    { label: 'Applications Submitted', value: data.applications_submitted, icon: CheckCircle2, page: 'applications', tone: 'success' },
    { label: 'Interview Invitations', value: data.interview_invitations, icon: CalendarCheck, page: 'interviews', tone: 'info' },
    { label: 'Rejected Applications', value: data.rejected_applications, icon: XCircle, page: 'applications', tone: 'danger' },
    { label: 'Submission Success Rate', value: `${data.success_statistics.submission_success_rate_pct}%`, icon: Activity, page: 'analytics', tone: 'accent' },
  ];

  const breakdownRows = Object.entries(data.status_breakdown).map(([status, count]) => ({
    label: status.replaceAll('_', ' '),
    value: count,
  }));

  return (
    <div className="stack-lg">
      {botStatus && (
        <section className="card">
          <div className="card-header" style={{ marginBottom: 0 }}>
            <div>
              <h3>Autonomous Engine: {botStatus.config.bot_paused ? 'Paused' : 'Running'}</h3>
              <p className="muted small">
                Auto-apply: {botStatus.config.auto_apply_paused ? 'Paused' : 'Active'} · Search every{' '}
                {Math.round(botStatus.config.search_frequency_minutes / 60)}h · Thresholds{' '}
                {botStatus.config.match_approval_threshold}% / {botStatus.config.match_strong_threshold}%
              </p>
            </div>
            <div className="actions-cell">
              {botStatus.config.bot_paused ? (
                <button
                  type="button"
                  className="btn btn-success btn-sm"
                  onClick={() => void api.resumeBot().then((cfg) => setBotStatus({ ...botStatus, config: cfg }))}
                >
                  <Play size={14} /> Resume Bot
                </button>
              ) : (
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  onClick={() => void api.pauseBot().then((cfg) => setBotStatus({ ...botStatus, config: cfg }))}
                >
                  <Pause size={14} /> Pause Bot
                </button>
              )}
              <button
                type="button"
                className="btn btn-primary btn-sm"
                onClick={() => void api.startManualSearch().then((r) => onNotify(`Search complete: ${r.created ?? 0} new, ${r.matched ?? 0} matched`))}
              >
                <Search size={14} /> Manual Search
              </button>
            </div>
          </div>
        </section>
      )}
      <div className="kpi-grid">
        {kpis.map((kpi) => {
          const Icon = kpi.icon;
          return (
            <button key={kpi.label} type="button" className={`card kpi-card tone-${kpi.tone}`} onClick={() => onNavigate(kpi.page)}>
              <div className="kpi-top">
                <span className="kpi-label">{kpi.label}</span>
                <Icon size={18} className="kpi-icon" />
              </div>
              <div className="kpi-value">{kpi.value}</div>
            </button>
          );
        })}
      </div>

      <div className="grid-2">
        <section className="card">
          <h3>Application Success Statistics</h3>
          <div className="stats-list">
            <div className="stat-row">
              <span>Submission success rate</span>
              <strong>{data.success_statistics.submission_success_rate_pct}%</strong>
            </div>
            <div className="stat-row">
              <span>Interview conversion rate</span>
              <strong>{data.success_statistics.interview_conversion_rate_pct}%</strong>
            </div>
            <div className="stat-row">
              <span>Owner approval rate</span>
              <strong>{data.success_statistics.approval_rate_pct}%</strong>
            </div>
            <div className="stat-row">
              <span>Total tracked applications</span>
              <strong>{data.success_statistics.total_applications}</strong>
            </div>
            <div className="stat-row">
              <span>Awaiting confirmation / manual review</span>
              <strong>{data.confirmation_pending}</strong>
            </div>
            <div className="stat-row">
              <span>Failed submissions</span>
              <strong>{data.failed_applications}</strong>
            </div>
          </div>
        </section>

        <BarChartCard
          title="Application pipeline breakdown"
          subtitle="Live counts by workflow status"
          data={breakdownRows}
        />
      </div>
    </div>
  );
}

export function AnalyticsPage({ onNotify }: { onNotify: (msg: string, isError?: boolean) => void }) {
  const [data, setData] = useState<AnalyticsData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    api
      .getAnalytics()
      .then((res) => {
        if (active) setData(res);
      })
      .catch((err) => onNotify(err instanceof Error ? err.message : 'Failed to load analytics', true))
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [onNotify]);

  if (loading) return <div className="card empty-state">Loading analytics...</div>;
  if (!data) return <div className="card empty-state">Unable to load analytics.</div>;

  return (
    <div className="stack-lg">
      <div className="grid-2">
        <VerticalColumnChartCard
          title="Opportunities discovered by week"
          subtitle="Weekly ingestion volume across active sources"
          data={data.opportunities_by_week.map((d) => ({ label: d.week, value: d.count }))}
          accent="var(--accent)"
        />
        <VerticalColumnChartCard
          title="Applications submitted"
          subtitle="Confirmed weekly submissions"
          data={data.applications_submitted.map((d) => ({ label: d.week, value: d.count }))}
          accent="var(--success)"
        />
      </div>

      <div className="grid-2">
        <BarChartCard
          title="Applications by category"
          subtitle="Distribution across target career domains"
          data={data.applications_by_category.map((d) => ({ label: d.category.replaceAll('_', ' '), value: d.count }))}
          accent="var(--info)"
        />
        <FunnelChartCard conversion={data.interview_conversion} />
      </div>

      <div className="grid-2">
        <BarChartCard
          title="Match distribution"
          subtitle="Candidate-to-opportunity score bands"
          data={data.match_distribution.map((d) => ({ label: d.range, value: d.count }))}
          accent="var(--warning)"
        />
        <SourcePerformanceCard sources={data.source_performance} />
      </div>
    </div>
  );
}
