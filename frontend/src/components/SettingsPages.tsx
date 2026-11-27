import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { Pause, Play, Plus, RefreshCw, Search, ShieldCheck, Trash2 } from 'lucide-react';
import {
  api,
  type AIConfigData,
  type AccountData,
  type BotStatusData,
  type JobSourceItem,
  type NotificationDeliveryItem,
  type NotificationSettingsData,
  type SavedSearchItem,
} from '../api/client';

export function SourcesPage({
  sources,
  onRefresh,
  onNotify,
}: {
  sources: JobSourceItem[];
  onRefresh: () => Promise<void>;
  onNotify: (msg: string, isError?: boolean) => void;
}) {
  const [name, setName] = useState('');
  const [baseUrl, setBaseUrl] = useState('');
  const [connectorType, setConnectorType] = useState('rss');
  const [feedUrl, setFeedUrl] = useState('');
  const [automationPermitted, setAutomationPermitted] = useState(false);

  async function handleCreate(e: FormEvent) {
    e.preventDefault();
    try {
      const config: Record<string, unknown> = { automation_permitted: automationPermitted };
      if (connectorType === 'rss') config.feed_url = feedUrl || baseUrl;
      if (connectorType === 'greenhouse') config.board_token = feedUrl || name.toLowerCase().replace(/\s+/g, '');
      if (connectorType === 'lever') config.site = feedUrl || name.toLowerCase().replace(/\s+/g, '');
      await api.createSource({ name, base_url: baseUrl, connector_type: connectorType, config });
      setName('');
      setBaseUrl('');
      setFeedUrl('');
      onNotify('Job source added');
      await onRefresh();
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'Failed to create source', true);
    }
  }

  return (
    <div className="stack-lg">
      <section className="card">
        <h3>Add Authorized Job Source</h3>
        <form onSubmit={handleCreate} className="filters-grid">
          <label className="field"><span>Source Name</span><input required value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Remotive" /></label>
          <label className="field"><span>Base URL</span><input required value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="https://remotive.com" /></label>
          <label className="field">
            <span>Connector</span>
            <select value={connectorType} onChange={(e) => setConnectorType(e.target.value)}>
              <option value="rss">RSS</option>
              <option value="remotive">Remotive</option>
              <option value="greenhouse">Greenhouse</option>
              <option value="lever">Lever</option>
              <option value="authorized_career_page">Authorized Career Page</option>
            </select>
          </label>
          <label className="field"><span>Feed URL / Board Token</span><input value={feedUrl} onChange={(e) => setFeedUrl(e.target.value)} placeholder="Optional feed URL or token" /></label>
          <div className="field align-end">
            <label className="checkbox-inline">
              <input type="checkbox" checked={automationPermitted} onChange={(e) => setAutomationPermitted(e.target.checked)} />
              <span>Permits automation</span>
            </label>
          </div>
          <div className="field align-end">
            <button type="submit" className="btn btn-primary"><Plus size={15} /> Add Source</button>
          </div>
        </form>
      </section>

      <section className="card">
        <h3>Configured Job Sources ({sources.length})</h3>
        {sources.length === 0 ? (
          <div className="empty-state">No job sources configured yet.</div>
        ) : (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Connector</th>
                  <th>Reliability</th>
                  <th>Automation</th>
                  <th>Status</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {sources.map((s) => (
                  <tr key={s.id}>
                    <td>
                      <strong>{s.name}</strong>
                      <div className="muted small">{s.base_url}</div>
                    </td>
                    <td><code>{s.connector_type}</code></td>
                    <td>{s.reliability_score}%</td>
                    <td><span className={`pill ${s.automation_permitted ? 'pill-success' : 'pill-neutral'}`}>{s.automation_permitted ? 'Permitted' : 'Manual only'}</span></td>
                    <td><span className={`pill ${s.is_active ? 'pill-success' : 'pill-neutral'}`}>{s.is_active ? 'Active' : 'Paused'}</span></td>
                    <td>
                      <div className="actions-cell">
                        <button type="button" className="btn btn-secondary btn-sm" onClick={() => void api.toggleSource(s.id).then(() => onRefresh())}>
                          {s.is_active ? 'Disable' : 'Enable'}
                        </button>
                        <button
                          type="button"
                          className="btn btn-primary btn-sm"
                          onClick={() => void api.runSource(s.id).then((r) => onNotify(`Fetched ${r.fetched_count}, created ${r.created_count}`))}
                        >
                          <Play size={13} /> Run
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}

export function SearchConfigPage({
  onApplySearch,
  onNotify,
}: {
  onApplySearch: (query: string) => void;
  onNotify: (msg: string, isError?: boolean) => void;
}) {
  const [searches, setSearches] = useState<SavedSearchItem[]>([]);
  const [name, setName] = useState('');
  const [query, setQuery] = useState('');
  const [location, setLocation] = useState('');
  const [remoteOnly, setRemoteOnly] = useState(false);

  const load = useCallback(async () => {
    try {
      setSearches(await api.listSavedSearches());
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'Failed to load saved searches', true);
    }
  }, [onNotify]);

  useEffect(() => {
    void load();
  }, [load]);

  async function handleCreate(e: FormEvent) {
    e.preventDefault();
    try {
      await api.createSavedSearch({
        name,
        query,
        filters: { location: location || undefined, remote_only: remoteOnly },
        is_active: true,
      });
      setName('');
      setQuery('');
      setLocation('');
      onNotify('Saved search created');
      await load();
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'Failed to create search', true);
    }
  }

  return (
    <div className="stack-lg">
      <section className="card">
        <h3>Create Search Configuration</h3>
        <form onSubmit={handleCreate} className="filters-grid">
          <label className="field"><span>Search Name</span><input required value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Remote Python" /></label>
          <label className="field"><span>Keywords</span><input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="python fastapi backend" /></label>
          <label className="field"><span>Preferred Location</span><input value={location} onChange={(e) => setLocation(e.target.value)} placeholder="Nairobi / Worldwide" /></label>
          <div className="field align-end">
            <label className="checkbox-inline">
              <input type="checkbox" checked={remoteOnly} onChange={(e) => setRemoteOnly(e.target.checked)} />
              <span>Remote only</span>
            </label>
          </div>
          <div className="field align-end">
            <button type="submit" className="btn btn-primary"><Plus size={15} /> Save Search</button>
          </div>
        </form>
      </section>

      <section className="card">
        <h3>Saved Search Profiles ({searches.length})</h3>
        {searches.length === 0 ? (
          <div className="empty-state">No saved searches yet.</div>
        ) : (
          <div className="stack-sm">
            {searches.map((s) => (
              <div key={s.id} className="list-row">
                <div>
                  <strong>{s.name}</strong>
                  <div className="muted small">Query: {s.query || 'Any'} · Filters: {JSON.stringify(s.filters)}</div>
                </div>
                <div className="actions-cell">
                  <button type="button" className="btn btn-secondary btn-sm" onClick={() => onApplySearch(s.query || '')}>
                    <Search size={13} /> Run Search
                  </button>
                  <button
                    type="button"
                    className="btn btn-secondary btn-sm"
                    onClick={() => void api.updateSavedSearch(s.id, { is_active: !s.is_active }).then(() => load())}
                  >
                    {s.is_active ? 'Pause' : 'Activate'}
                  </button>
                  <button type="button" className="btn btn-ghost btn-sm" onClick={() => void api.deleteSavedSearch(s.id).then(() => load())}>
                    <Trash2 size={14} />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

export function AIConfigPage({ onNotify }: { onNotify: (msg: string, isError?: boolean) => void }) {
  const [config, setConfig] = useState<AIConfigData | null>(null);
  const [botStatus, setBotStatus] = useState<BotStatusData | null>(null);
  const [workAuth, setWorkAuth] = useState('');
  const [locations, setLocations] = useState('');
  const [remoteOnly, setRemoteOnly] = useState(false);
  const [oppTypes, setOppTypes] = useState('');
  const [careerPrefs, setCareerPrefs] = useState('');
  const [searchFreq, setSearchFreq] = useState(360);
  const [strongThreshold, setStrongThreshold] = useState(85);
  const [approvalThreshold, setApprovalThreshold] = useState(65);
  const [running, setRunning] = useState(false);

  const loadAll = useCallback(async () => {
    try {
      const [res, bot] = await Promise.all([api.getAIConfig(), api.getBotStatus().catch(() => null)]);
      setConfig(res);
      setWorkAuth(res.preferences.work_authorization || '');
      setLocations(res.preferences.preferred_locations || '');
      setRemoteOnly(res.preferences.remote_only);
      setOppTypes(res.preferences.opportunity_types || '');
      setCareerPrefs(res.preferences.career_preferences || '');
      if (bot) {
        setBotStatus(bot);
        setSearchFreq(bot.config.search_frequency_minutes);
        setStrongThreshold(bot.config.match_strong_threshold);
        setApprovalThreshold(bot.config.match_approval_threshold);
      }
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'Failed to load AI configuration', true);
    }
  }, [onNotify]);

  useEffect(() => {
    void loadAll();
  }, [loadAll]);

  async function handleSave(e: FormEvent) {
    e.preventDefault();
    try {
      const updated = await api.updateAIConfig({
        work_authorization: workAuth || null,
        preferred_locations: locations || null,
        remote_only: remoteOnly,
        opportunity_types: oppTypes || null,
        career_preferences: careerPrefs || null,
      });
      setConfig(updated);
      onNotify('AI matching preferences saved');
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'Failed to update AI preferences', true);
    }
  }

  async function handleSaveBotConfig(e: FormEvent) {
    e.preventDefault();
    try {
      await api.updateBotConfig({
        search_frequency_minutes: searchFreq,
        match_strong_threshold: strongThreshold,
        match_approval_threshold: approvalThreshold,
      });
      onNotify('Autonomous schedule & match thresholds updated');
      await loadAll();
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'Failed to update bot configuration', true);
    }
  }

  async function handleRunMatching() {
    setRunning(true);
    try {
      const res = await api.runMatching();
      onNotify(`Re-scored ${res.processed} opportunities`);
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'Matching run failed', true);
    } finally {
      setRunning(false);
    }
  }

  if (!config) return <div className="card empty-state">Loading AI configuration...</div>;

  return (
    <div className="stack-lg">
      {botStatus && (
        <section className="card">
          <div className="card-header">
            <div>
              <h3>Autonomous Bot &amp; Worker Controls</h3>
              <p className="muted small">
                Redis: <strong>{botStatus.health.redis_status}</strong> · Active tasks: <strong>{botStatus.health.active_tasks.length}</strong>
              </p>
            </div>
            <div className="actions-cell">
              {botStatus.config.bot_paused ? (
                <button type="button" className="btn btn-success btn-sm" onClick={() => void api.resumeBot().then(() => loadAll())}>
                  <Play size={14} /> Resume Bot
                </button>
              ) : (
                <button type="button" className="btn btn-danger btn-sm" onClick={() => void api.pauseBot().then(() => loadAll())}>
                  <Pause size={14} /> Pause Bot
                </button>
              )}
              {botStatus.config.auto_apply_paused ? (
                <button type="button" className="btn btn-secondary btn-sm" onClick={() => void api.resumeAutoApply().then(() => loadAll())}>
                  <Play size={14} /> Resume Auto-Apply
                </button>
              ) : (
                <button type="button" className="btn btn-secondary btn-sm" onClick={() => void api.pauseAutoApply().then(() => loadAll())}>
                  <Pause size={14} /> Pause Auto-Apply
                </button>
              )}
              <button
                type="button"
                className="btn btn-primary btn-sm"
                onClick={() => void api.startManualSearch().then((r) => { onNotify(`Manual search: ${r.created ?? 0} new, ${r.matched ?? 0} matched`); void loadAll(); })}
              >
                <Search size={14} /> Start Manual Search
              </button>
            </div>
          </div>

          <form onSubmit={handleSaveBotConfig} className="filters-grid">
            <label className="field">
              <span>Search Frequency</span>
              <select aria-label="Search frequency" value={searchFreq} onChange={(e) => setSearchFreq(Number(e.target.value))}>
                <option value={60}>Every 1 hour</option>
                <option value={180}>Every 3 hours</option>
                <option value={360}>Every 6 hours (Default)</option>
                <option value={720}>Every 12 hours</option>
                <option value={1440}>Daily (24 hours)</option>
              </select>
            </label>
            <label className="field">
              <span>Strong Match Threshold (%)</span>
              <input type="number" min={50} max={100} value={strongThreshold} onChange={(e) => setStrongThreshold(Number(e.target.value))} />
            </label>
            <label className="field">
              <span>Approval Threshold (%)</span>
              <input type="number" min={0} max={99} value={approvalThreshold} onChange={(e) => setApprovalThreshold(Number(e.target.value))} />
            </label>
            <div className="field align-end">
              <button type="submit" className="btn btn-primary">Save Bot Thresholds</button>
            </div>
          </form>

          {botStatus.recent_runs.length > 0 && (
            <div className="table-wrap" style={{ marginTop: 14 }}>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Task</th>
                    <th>Queue</th>
                    <th>Status</th>
                    <th>Attempt</th>
                    <th>Duration</th>
                  </tr>
                </thead>
                <tbody>
                  {botStatus.recent_runs.slice(0, 6).map((run) => (
                    <tr key={run.id}>
                      <td><strong>{run.bot_name}</strong></td>
                      <td><code>{run.queue_name}</code></td>
                      <td><span className={`pill status-${run.status}`}>{run.status}</span></td>
                      <td>{run.attempt}</td>
                      <td>{run.duration_ms !== null ? `${run.duration_ms}ms` : '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}

      <div className="grid-2">
        <section className="card">
          <h3>Active Provider &amp; Decision Thresholds</h3>
          <div className="stats-list">
            <div className="stat-row"><span>Provider</span><strong>{config.ai_provider}</strong></div>
            <div className="stat-row"><span>Model</span><strong>{config.ai_model}</strong></div>
            <div className="stat-row"><span>Automatic consideration threshold</span><strong>{strongThreshold}+</strong></div>
            <div className="stat-row"><span>Approval queue threshold</span><strong>{approvalThreshold}–{strongThreshold - 1}</strong></div>
          </div>
          <div style={{ marginTop: 16 }}>
            <button type="button" className="btn btn-primary" disabled={running} onClick={() => void handleRunMatching()}>
              <RefreshCw size={15} /> {running ? 'Running Matching...' : 'Re-score Opportunities Now'}
            </button>
          </div>
        </section>

        <section className="card">
          <h3>Scoring Weights</h3>
          <div className="stats-list">
            {Object.entries(config.weights).map(([key, weight]) => (
              <div key={key} className="stat-row">
                <span style={{ textTransform: 'capitalize' }}>{key}</span>
                <strong>{weight}%</strong>
              </div>
            ))}
          </div>
        </section>
      </div>

      <section className="card">
        <h3>Candidate Matching &amp; Eligibility Rules</h3>
        <form onSubmit={handleSave} className="stack">
          <div className="grid-2">
            <label className="field"><span>Work Authorization</span><input value={workAuth} onChange={(e) => setWorkAuth(e.target.value)} placeholder="e.g. Authorized in Kenya / Remote" /></label>
            <label className="field"><span>Preferred Locations</span><input value={locations} onChange={(e) => setLocations(e.target.value)} placeholder="Nairobi, Remote" /></label>
            <label className="field"><span>Opportunity Types</span><input value={oppTypes} onChange={(e) => setOppTypes(e.target.value)} placeholder="internship, full-time, contract" /></label>
            <label className="field"><span>Target Titles / Career Preferences</span><input value={careerPrefs} onChange={(e) => setCareerPrefs(e.target.value)} placeholder="Backend Engineer, Python Developer" /></label>
          </div>
          <label className="checkbox-inline">
            <input type="checkbox" checked={remoteOnly} onChange={(e) => setRemoteOnly(e.target.checked)} />
            <span>Restrict eligibility to remote-only opportunities</span>
          </label>
          <div>
            <button type="submit" className="btn btn-primary">Save AI Configuration</button>
          </div>
        </form>
      </section>
    </div>
  );
}

export function NotificationSettingsPage({ onNotify }: { onNotify: (msg: string, isError?: boolean) => void }) {
  const [settings, setSettings] = useState<NotificationSettingsData | null>(null);
  const [deliveries, setDeliveries] = useState<NotificationDeliveryItem[]>([]);

  const load = useCallback(async () => {
    try {
      const [cfg, logs] = await Promise.all([api.getNotificationSettings(), api.listNotificationDeliveries()]);
      setSettings(cfg);
      setDeliveries(logs);
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'Failed to load notification settings', true);
    }
  }, [onNotify]);

  useEffect(() => {
    void load();
  }, [load]);

  async function handleSave(e: FormEvent) {
    e.preventDefault();
    if (!settings) return;
    try {
      const updated = await api.updateNotificationSettings(settings);
      setSettings(updated);
      onNotify('Notification preferences updated');
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'Failed to save notification preferences', true);
    }
  }

  if (!settings) return <div className="card empty-state">Loading notification settings...</div>;

  return (
    <div className="stack-lg">
      <section className="card">
        <h3>Channels, Frequency &amp; Score Threshold</h3>
        <form onSubmit={handleSave} className="stack">
          <div className="grid-2">
            <label className="checkbox-inline">
              <input
                type="checkbox"
                checked={settings.telegram_enabled}
                onChange={(e) => setSettings({ ...settings, telegram_enabled: e.target.checked })}
              />
              <span>Enable Telegram Bot Notifications</span>
            </label>
            <label className="checkbox-inline">
              <input
                type="checkbox"
                checked={settings.email_notifications_enabled}
                onChange={(e) => setSettings({ ...settings, email_notifications_enabled: e.target.checked })}
              />
              <span>Enable SMTP Email Notifications</span>
            </label>
            <label className="field">
              <span>Telegram Chat ID</span>
              <input
                value={settings.telegram_chat_id || ''}
                onChange={(e) => setSettings({ ...settings, telegram_chat_id: e.target.value })}
                placeholder="e.g. 987654321"
              />
            </label>
            <label className="field">
              <span>Notification Frequency</span>
              <select
                value={settings.notification_frequency}
                onChange={(e) => setSettings({ ...settings, notification_frequency: e.target.value })}
              >
                <option value="immediate">Immediate</option>
                <option value="daily">Daily summary</option>
                <option value="weekly">Weekly summary</option>
              </select>
            </label>
            <label className="field">
              <span>Minimum Match Score ({settings.min_notification_match_score}%)</span>
              <input
                type="number"
                min={0}
                max={100}
                value={settings.min_notification_match_score}
                onChange={(e) => setSettings({ ...settings, min_notification_match_score: Number(e.target.value) })}
              />
            </label>
          </div>

          <div className="grid-2">
            {Object.entries(settings.categories).map(([channel, events]) => (
              <div key={channel} className="subcard">
                <h4 style={{ textTransform: 'capitalize' }}>{channel} Categories</h4>
                <div className="stack-sm">
                  {Object.entries(events).map(([eventType, enabled]) => (
                    <label key={`${channel}-${eventType}`} className="checkbox-inline">
                      <input
                        type="checkbox"
                        checked={enabled}
                        onChange={(e) =>
                          setSettings({
                            ...settings,
                            categories: {
                              ...settings.categories,
                              [channel]: { ...settings.categories[channel], [eventType]: e.target.checked },
                            },
                          })
                        }
                      />
                      <span>{eventType.replaceAll('_', ' ')}</span>
                    </label>
                  ))}
                </div>
              </div>
            ))}
          </div>

          <div>
            <button type="submit" className="btn btn-primary">Save Notification Settings</button>
          </div>
        </form>
      </section>

      <section className="card">
        <div className="card-header">
          <h3>Delivery Logs ({deliveries.length})</h3>
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={() => void api.retryNotifications().then((r) => { onNotify(`Retried ${r.retried}, sent ${r.sent}`); void load(); })}
          >
            <RefreshCw size={14} /> Retry Failed
          </button>
        </div>
        {deliveries.length === 0 ? (
          <div className="empty-state">No notification deliveries logged yet.</div>
        ) : (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Channel</th>
                  <th>Category</th>
                  <th>Status</th>
                  <th>Attempts</th>
                  <th>Last Error</th>
                </tr>
              </thead>
              <tbody>
                {deliveries.slice(0, 20).map((d) => (
                  <tr key={d.id}>
                    <td>{d.channel}</td>
                    <td>{d.event_type.replaceAll('_', ' ')}</td>
                    <td><span className={`pill status-${d.status}`}>{d.status}</span></td>
                    <td>{d.attempts}/{d.max_attempts}</td>
                    <td className="small muted">{d.last_error || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}

export function AccountSettingsPage({
  onUserUpdated,
  onLoggedOut,
  onNotify,
}: {
  onUserUpdated: () => Promise<void>;
  onLoggedOut: () => void;
  onNotify: (msg: string, isError?: boolean) => void;
}) {
  const [account, setAccount] = useState<AccountData | null>(null);
  const [firstName, setFirstName] = useState('');
  const [lastName, setLastName] = useState('');
  const [timezone, setTimezone] = useState('UTC');
  const [locale, setLocale] = useState('en');
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');

  useEffect(() => {
    api
      .getAccount()
      .then((res) => {
        setAccount(res);
        setFirstName(res.first_name);
        setLastName(res.last_name);
        setTimezone(res.timezone);
        setLocale(res.locale);
      })
      .catch((err) => onNotify(err instanceof Error ? err.message : 'Failed to load account', true));
  }, [onNotify]);

  async function handleSaveAccount(e: FormEvent) {
    e.preventDefault();
    try {
      const updated = await api.updateAccount({ first_name: firstName, last_name: lastName, timezone, locale });
      setAccount(updated);
      await onUserUpdated();
      onNotify('Account settings saved');
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'Failed to update account', true);
    }
  }

  async function handleChangePassword(e: FormEvent) {
    e.preventDefault();
    try {
      await api.changePassword(currentPassword, newPassword);
      setCurrentPassword('');
      setNewPassword('');
      onNotify('Password updated');
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'Password change failed', true);
    }
  }

  if (!account) return <div className="card empty-state">Loading account settings...</div>;

  return (
    <div className="stack-lg">
      <div className="grid-2">
        <section className="card">
          <h3>Owner Account</h3>
          <form onSubmit={handleSaveAccount} className="stack">
            <label className="field"><span>Email</span><input disabled value={account.email} /></label>
            <div className="grid-2">
              <label className="field"><span>First Name</span><input required value={firstName} onChange={(e) => setFirstName(e.target.value)} /></label>
              <label className="field"><span>Last Name</span><input required value={lastName} onChange={(e) => setLastName(e.target.value)} /></label>
              <label className="field"><span>Timezone</span><input value={timezone} onChange={(e) => setTimezone(e.target.value)} /></label>
              <label className="field"><span>Locale</span><input value={locale} onChange={(e) => setLocale(e.target.value)} /></label>
            </div>
            <div><button type="submit" className="btn btn-primary">Save Account</button></div>
          </form>
        </section>

        <section className="card">
          <h3>Change Password</h3>
          <form onSubmit={handleChangePassword} className="stack">
            <label className="field"><span>Current Password</span><input type="password" required value={currentPassword} onChange={(e) => setCurrentPassword(e.target.value)} /></label>
            <label className="field"><span>New Password (12+ chars)</span><input type="password" required value={newPassword} onChange={(e) => setNewPassword(e.target.value)} /></label>
            <div className="inline-row">
              <button type="submit" className="btn btn-secondary"><ShieldCheck size={15} /> Update Password</button>
              <button type="button" className="btn btn-danger" onClick={() => void api.logout().then(onLoggedOut)}>Sign Out</button>
            </div>
          </form>
        </section>
      </div>

      <section className="card">
        <h3>Active Sessions ({account.active_sessions.length})</h3>
        <div className="stack-sm">
          {account.active_sessions.map((s) => (
            <div key={s.id} className="list-row">
              <span><strong>{s.ip_address || 'Local session'}</strong> · {s.user_agent || 'Browser'}</span>
              <span className="muted small">Expires {new Date(s.expires_at).toLocaleDateString()}</span>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
