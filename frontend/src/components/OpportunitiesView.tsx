import { useCallback, useEffect, useState } from 'react';
import { ExternalLink, Filter, Search, Sparkles } from 'lucide-react';
import { api, type JobSourceItem, type OpportunitiesResponse, type OpportunityItem } from '../api/client';

function formatDate(iso: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleDateString();
}

export function OpportunitiesView({
  recommendedOnly,
  initialQuery = '',
  sources,
  onNavigate,
  onNotify,
}: {
  recommendedOnly: boolean;
  initialQuery?: string;
  sources: JobSourceItem[];
  onNavigate: (page: string) => void;
  onNotify: (msg: string, isError?: boolean) => void;
}) {
  const [q, setQ] = useState(initialQuery);
  const [location, setLocation] = useState('');
  const [remoteOnly, setRemoteOnly] = useState(false);
  const [sourceId, setSourceId] = useState('');
  const [applicationStatus, setApplicationStatus] = useState('');
  const [minScore, setMinScore] = useState(recommendedOnly ? '65' : '');
  const [sortBy, setSortBy] = useState('score');
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc');
  const [page, setPage] = useState(1);
  const [data, setData] = useState<OpportunitiesResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);

  useEffect(() => {
    if (initialQuery) setQ(initialQuery);
  }, [initialQuery]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (q.trim()) params.set('q', q.trim());
      if (location.trim()) params.set('location', location.trim());
      if (remoteOnly) params.set('remote_only', 'true');
      if (sourceId) params.set('source_id', sourceId);
      if (applicationStatus) params.set('application_status', applicationStatus);
      if (recommendedOnly) params.set('recommended_only', 'true');
      if (minScore) params.set('min_score', minScore);
      params.set('sort_by', sortBy);
      params.set('sort_dir', sortDir);
      params.set('page', String(page));
      params.set('page_size', '10');
      setData(await api.listOpportunities(params));
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'Failed to load opportunities', true);
    } finally {
      setLoading(false);
    }
  }, [q, location, remoteOnly, sourceId, applicationStatus, recommendedOnly, minScore, sortBy, sortDir, page, onNotify]);

  useEffect(() => {
    void load();
  }, [load]);

  async function handlePrepare(item: OpportunityItem) {
    setBusyId(item.id);
    try {
      const res = await api.generateAndPrepare(item.id);
      onNotify(`Application prepared (${res.status}) for ${item.title}`);
      await load();
      if (res.status === 'pending_approval') onNavigate('approvals');
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'Failed to prepare application', true);
    } finally {
      setBusyId(null);
    }
  }

  async function handleAnalyze(item: OpportunityItem) {
    setBusyId(item.id);
    try {
      await api.analyzeMatch(item.id);
      onNotify(`Match refreshed for ${item.title}`);
      await load();
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'Match analysis failed', true);
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="stack-lg">
      <section className="card">
        <div className="filters-grid">
          <label className="field">
            <span>Search</span>
            <div className="input-icon">
              <Search size={15} />
              <input
                aria-label="Search opportunities"
                value={q}
                onChange={(e) => {
                  setPage(1);
                  setQ(e.target.value);
                }}
                placeholder="Role, company, or skill..."
              />
            </div>
          </label>
          <label className="field">
            <span>Location</span>
            <input
              aria-label="Filter by location"
              value={location}
              onChange={(e) => {
                setPage(1);
                setLocation(e.target.value);
              }}
              placeholder="e.g. Nairobi, Remote"
            />
          </label>
          <label className="field">
            <span>Source</span>
            <select
              aria-label="Filter by source"
              value={sourceId}
              onChange={(e) => {
                setPage(1);
                setSourceId(e.target.value);
              }}
            >
              <option value="">All sources</option>
              {sources.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Status</span>
            <select
              aria-label="Filter by application status"
              value={applicationStatus}
              onChange={(e) => {
                setPage(1);
                setApplicationStatus(e.target.value);
              }}
            >
              <option value="">All statuses</option>
              <option value="discovered">Discovered</option>
              <option value="pending_approval">Pending approval</option>
              <option value="approved">Approved</option>
              <option value="ready_to_submit">Ready to submit</option>
              <option value="submitted">Submitted</option>
              <option value="rejected">Rejected</option>
              <option value="failed">Failed</option>
            </select>
          </label>
          <label className="field">
            <span>Min score</span>
            <input
              type="number"
              min={0}
              max={100}
              aria-label="Minimum match score"
              value={minScore}
              onChange={(e) => {
                setPage(1);
                setMinScore(e.target.value);
              }}
            />
          </label>
          <label className="field">
            <span>Sort by</span>
            <div className="inline-row">
              <select aria-label="Sort opportunities" value={sortBy} onChange={(e) => setSortBy(e.target.value)}>
                <option value="score">Match score</option>
                <option value="posted_at">Posted date</option>
                <option value="deadline">Deadline</option>
                <option value="salary_max">Salary</option>
                <option value="company">Employer</option>
              </select>
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={() => setSortDir((d) => (d === 'desc' ? 'asc' : 'desc'))}
                aria-label="Toggle sort direction"
              >
                {sortDir === 'desc' ? 'Desc' : 'Asc'}
              </button>
            </div>
          </label>
        </div>
        <div className="filter-footer">
          <label className="checkbox-inline">
            <input
              type="checkbox"
              checked={remoteOnly}
              onChange={(e) => {
                setPage(1);
                setRemoteOnly(e.target.checked);
              }}
            />
            <span>Remote only</span>
          </label>
          <span className="muted small">
            <Filter size={13} /> {data ? `${data.total} opportunities` : 'Loading...'}
          </span>
        </div>
      </section>

      <section className="card">
        {loading ? (
          <div className="empty-state">Loading opportunities...</div>
        ) : !data || data.items.length === 0 ? (
          <div className="empty-state">No opportunities matched your current filters.</div>
        ) : (
          <>
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Role &amp; Employer</th>
                    <th>Match Score</th>
                    <th>Location</th>
                    <th>Salary</th>
                    <th>Deadline</th>
                    <th>Status</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((item) => (
                    <tr key={item.id}>
                      <td>
                        <div className="cell-title">
                          <strong>{item.title}</strong>
                          <span className="muted small">
                            {item.company} {item.source_name ? `· ${item.source_name}` : ''}
                          </span>
                        </div>
                      </td>
                      <td>
                        {item.match_score !== null ? (
                          <span
                            className={`pill ${
                              item.match_score >= 85 ? 'pill-success' : item.match_score >= 65 ? 'pill-warning' : 'pill-neutral'
                            }`}
                          >
                            {item.match_score}%
                          </span>
                        ) : (
                          <span className="pill pill-neutral">Unscored</span>
                        )}
                      </td>
                      <td>{item.location || (item.remote_only ? 'Remote' : 'Unspecified')}</td>
                      <td>{item.salary_text || (item.salary_max ? `${item.salary_currency || ''} ${item.salary_max}` : '—')}</td>
                      <td>{formatDate(item.deadline)}</td>
                      <td>
                        <span className={`pill status-${item.application_status}`}>{item.application_status.replaceAll('_', ' ')}</span>
                      </td>
                      <td>
                        <div className="actions-cell">
                          <button
                            type="button"
                            className="btn btn-secondary btn-sm"
                            disabled={busyId === item.id}
                            onClick={() => void handleAnalyze(item)}
                          >
                            <Sparkles size={13} /> Analyze
                          </button>
                          <button
                            type="button"
                            className="btn btn-primary btn-sm"
                            disabled={busyId === item.id}
                            onClick={() => void handlePrepare(item)}
                          >
                            Prepare
                          </button>
                          <a href={item.url} target="_blank" rel="noreferrer" className="btn btn-ghost btn-sm" aria-label={`Open ${item.title}`}>
                            <ExternalLink size={13} />
                          </a>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="pagination">
              <span className="muted small">
                Page {data.page} of {data.total_pages}
              </span>
              <div className="inline-row">
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  disabled={page <= 1}
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                >
                  Previous
                </button>
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  disabled={page >= data.total_pages}
                  onClick={() => setPage((p) => p + 1)}
                >
                  Next
                </button>
              </div>
            </div>
          </>
        )}
      </section>
    </div>
  );
}
