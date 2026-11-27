import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { CalendarPlus, Check, Download, Eye, Play, RefreshCw, Send, Trash2, Upload } from 'lucide-react';
import {
  api,
  type ApplicationReviewItem,
  type DiscoveryHistoryItem,
  type DocumentItem,
  type InterviewItem,
  type JobSourceItem,
  type ProfileData,
  type ProfileFactItem,
} from '../api/client';

export function DiscoveryPage({
  sources,
  onNotify,
}: {
  sources: JobSourceItem[];
  onNotify: (msg: string, isError?: boolean) => void;
}) {
  const [history, setHistory] = useState<DiscoveryHistoryItem[]>([]);
  const [selectedSource, setSelectedSource] = useState('');
  const [runMatching, setRunMatching] = useState(true);
  const [running, setRunning] = useState(false);

  const load = useCallback(async () => {
    try {
      setHistory(await api.getDiscoveryHistory());
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'Failed to load discovery history', true);
    }
  }, [onNotify]);

  useEffect(() => {
    void load();
  }, [load]);

  async function handleDiscover(e: FormEvent) {
    e.preventDefault();
    setRunning(true);
    try {
      const res = await api.triggerDiscovery(selectedSource || null, runMatching);
      onNotify(`Discovery finished: ${res.created} new, ${res.updated} updated, ${res.matched} matched`);
      await load();
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'Discovery run failed', true);
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="stack-lg">
      <section className="card">
        <h3>Run Opportunity Discovery</h3>
        <p className="muted">Fetch openings from authorized job sources and optionally score matches against your career profile.</p>
        <form onSubmit={handleDiscover} className="inline-form">
          <select aria-label="Select job source" value={selectedSource} onChange={(e) => setSelectedSource(e.target.value)}>
            <option value="">All active sources</option>
            {sources.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name} ({s.connector_type})
              </option>
            ))}
          </select>
          <label className="checkbox-inline">
            <input type="checkbox" checked={runMatching} onChange={(e) => setRunMatching(e.target.checked)} />
            <span>Run AI matching afterward</span>
          </label>
          <button type="submit" className="btn btn-primary" disabled={running}>
            <Play size={15} /> {running ? 'Discovering...' : 'Run Discovery'}
          </button>
        </form>
      </section>

      <section className="card">
        <div className="card-header">
          <h3>Recent Discovery Runs</h3>
          <button type="button" className="btn btn-secondary btn-sm" onClick={() => void load()}>
            <RefreshCw size={14} /> Refresh
          </button>
        </div>
        {history.length === 0 ? (
          <div className="empty-state">No source discovery runs recorded yet.</div>
        ) : (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Source</th>
                  <th>Status</th>
                  <th>Fetched</th>
                  <th>Created</th>
                  <th>Updated</th>
                  <th>Started</th>
                </tr>
              </thead>
              <tbody>
                {history.map((row) => (
                  <tr key={row.id}>
                    <td><strong>{row.source_name}</strong></td>
                    <td><span className={`pill status-${row.status}`}>{row.status}</span></td>
                    <td>{row.fetched_count}</td>
                    <td>{row.created_count}</td>
                    <td>{row.updated_count}</td>
                    <td>{new Date(row.started_at).toLocaleString()}</td>
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

export function ApplicationHistoryPage({ onNotify }: { onNotify: (msg: string, isError?: boolean) => void }) {
  const [items, setItems] = useState<ApplicationReviewItem[]>([]);
  const [counts, setCounts] = useState<{ total: number; submitted: number; prepared_not_submitted: number }>({
    total: 0,
    submitted: 0,
    prepared_not_submitted: 0,
  });
  const [statusFilter, setStatusFilter] = useState('');
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.listApplications(statusFilter || undefined);
      setItems(res.items);
      setCounts(res.counts);
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'Failed to load application history', true);
    } finally {
      setLoading(false);
    }
  }, [statusFilter, onNotify]);

  useEffect(() => {
    void load();
  }, [load]);

  async function handleSubmit(id: string) {
    setBusyId(id);
    try {
      const res = await api.submitApplication(id);
      onNotify(`Submission result: ${res.status}${res.confirmation_reference ? ` (${res.confirmation_reference})` : ''}`);
      await load();
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'Submission failed', true);
    } finally {
      setBusyId(null);
    }
  }

  async function handleWithdraw(id: string) {
    setBusyId(id);
    try {
      await api.withdrawApplication(id);
      onNotify('Application withdrawn');
      await load();
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'Withdraw failed', true);
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="stack-lg">
      <div className="kpi-grid compact">
        <div className="card kpi-card">
          <span className="kpi-label">Total Tracked</span>
          <div className="kpi-value">{counts.total}</div>
        </div>
        <div className="card kpi-card tone-success">
          <span className="kpi-label">Submitted</span>
          <div className="kpi-value">{counts.submitted}</div>
        </div>
        <div className="card kpi-card tone-warning">
          <span className="kpi-label">Prepared (Not Submitted)</span>
          <div className="kpi-value">{counts.prepared_not_submitted}</div>
        </div>
      </div>

      <section className="card">
        <div className="card-header">
          <h3>Application History</h3>
          <select aria-label="Filter applications by status" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
            <option value="">All statuses</option>
            <option value="pending_approval">Pending approval</option>
            <option value="approved">Approved</option>
            <option value="ready_to_submit">Ready to submit</option>
            <option value="submitted">Submitted</option>
            <option value="confirmation_pending">Confirmation pending</option>
            <option value="failed">Failed</option>
            <option value="rejected">Rejected</option>
            <option value="withdrawn">Withdrawn</option>
            <option value="expired">Expired</option>
          </select>
        </div>

        {loading ? (
          <div className="empty-state">Loading applications...</div>
        ) : items.length === 0 ? (
          <div className="empty-state">No applications found.</div>
        ) : (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Role &amp; Employer</th>
                  <th>Match</th>
                  <th>Status</th>
                  <th>Confirmation Ref</th>
                  <th>Notes / Error</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {items.map((app) => (
                  <tr key={app.id}>
                    <td>
                      <strong>{app.title}</strong>
                      <div className="muted small">{app.company}</div>
                    </td>
                    <td>{app.match_score !== null ? `${app.match_score}%` : '—'}</td>
                    <td><span className={`pill status-${app.status}`}>{app.status.replaceAll('_', ' ')}</span></td>
                    <td><code>{app.confirmation_reference || '—'}</code></td>
                    <td className="small muted">{app.last_error || (app.submitted_at ? `Submitted ${new Date(app.submitted_at).toLocaleDateString()}` : '—')}</td>
                    <td>
                      <div className="actions-cell">
                        {(app.status === 'approved' || app.status === 'ready_to_submit') && (
                          <button type="button" className="btn btn-primary btn-sm" disabled={busyId === app.id} onClick={() => void handleSubmit(app.id)}>
                            <Send size={13} /> Submit
                          </button>
                        )}
                        {app.status !== 'withdrawn' && (
                          <button type="button" className="btn btn-secondary btn-sm" disabled={busyId === app.id} onClick={() => void handleWithdraw(app.id)}>
                            Withdraw
                          </button>
                        )}
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

export function InterviewTrackerPage({ onNotify }: { onNotify: (msg: string, isError?: boolean) => void }) {
  const [interviews, setInterviews] = useState<InterviewItem[]>([]);
  const [apps, setApps] = useState<ApplicationReviewItem[]>([]);
  const [applicationId, setApplicationId] = useState('');
  const [scheduledAt, setScheduledAt] = useState('');
  const [interviewType, setInterviewType] = useState('Technical Interview');
  const [notes, setNotes] = useState('');

  const load = useCallback(async () => {
    try {
      const [ivList, appRes] = await Promise.all([api.listInterviews(), api.listApplications()]);
      setInterviews(ivList);
      setApps(appRes.items);
      if (!applicationId && appRes.items.length > 0) setApplicationId(appRes.items[0].id);
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'Failed to load interviews', true);
    }
  }, [applicationId, onNotify]);

  useEffect(() => {
    void load();
  }, [load]);

  async function handleCreate(e: FormEvent) {
    e.preventDefault();
    try {
      await api.createInterview({
        application_id: applicationId,
        scheduled_at: new Date(scheduledAt).toISOString(),
        interview_type: interviewType,
        notes,
      });
      setNotes('');
      onNotify('Interview scheduled and notification queued');
      await load();
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'Failed to schedule interview', true);
    }
  }

  async function handleDelete(id: string) {
    try {
      await api.deleteInterview(id);
      onNotify('Interview removed');
      await load();
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'Failed to remove interview', true);
    }
  }

  return (
    <div className="stack-lg">
      <section className="card">
        <h3>Schedule / Record Interview Invitation</h3>
        <form onSubmit={handleCreate} className="filters-grid">
          <label className="field">
            <span>Application</span>
            <select required value={applicationId} onChange={(e) => setApplicationId(e.target.value)}>
              <option value="">Select application...</option>
              {apps.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.title} · {a.company}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Date &amp; Time</span>
            <input type="datetime-local" required value={scheduledAt} onChange={(e) => setScheduledAt(e.target.value)} />
          </label>
          <label className="field">
            <span>Interview Type</span>
            <input value={interviewType} onChange={(e) => setInterviewType(e.target.value)} placeholder="Technical / HR" />
          </label>
          <label className="field">
            <span>Notes</span>
            <input value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Meeting link or panel details" />
          </label>
          <div className="field align-end">
            <button type="submit" className="btn btn-primary" disabled={!applicationId}>
              <CalendarPlus size={15} /> Add Interview
            </button>
          </div>
        </form>
      </section>

      <section className="card">
        <h3>Upcoming &amp; Recorded Interviews</h3>
        {interviews.length === 0 ? (
          <div className="empty-state">No interviews recorded yet.</div>
        ) : (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Role &amp; Employer</th>
                  <th>Type</th>
                  <th>Scheduled</th>
                  <th>Notes</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {interviews.map((iv) => (
                  <tr key={iv.id}>
                    <td>
                      <strong>{iv.title}</strong>
                      <div className="muted small">{iv.company}</div>
                    </td>
                    <td>{iv.interview_type || 'Interview'}</td>
                    <td>{new Date(iv.scheduled_at).toLocaleString()}</td>
                    <td className="small">{iv.notes || '—'}</td>
                    <td>
                      <button type="button" className="btn btn-ghost btn-sm" onClick={() => void handleDelete(iv.id)} aria-label="Delete interview">
                        <Trash2 size={14} />
                      </button>
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

export function DocumentsPage({ onNotify }: { onNotify: (msg: string, isError?: boolean) => void }) {
  const [docs, setDocs] = useState<DocumentItem[]>([]);
  const [previewText, setPreviewText] = useState<string | null>(null);
  const [previewTitle, setPreviewTitle] = useState('');
  const [category, setCategory] = useState('cv');
  const [isDefault, setIsDefault] = useState(true);
  const [file, setFile] = useState<File | null>(null);

  const load = useCallback(async () => {
    try {
      setDocs(await api.listDocuments());
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'Failed to load documents', true);
    }
  }, [onNotify]);

  useEffect(() => {
    void load();
  }, [load]);

  async function handleUpload(e: FormEvent) {
    e.preventDefault();
    if (!file) return;
    const form = new FormData();
    form.append('file', file);
    form.append('category', category);
    form.append('is_default', String(isDefault));
    try {
      await api.uploadDocument(form);
      setFile(null);
      onNotify('Document uploaded and parsed');
      await load();
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'Upload failed', true);
    }
  }

  async function handlePreview(doc: DocumentItem) {
    try {
      setPreviewTitle(doc.name);
      setPreviewText(await api.previewDocument(doc.id));
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'Preview failed', true);
    }
  }

  return (
    <div className="stack-lg">
      <section className="card">
        <h3>Upload CV or Supporting Document (PDF / DOCX)</h3>
        <form onSubmit={handleUpload} className="inline-form">
          <input type="file" accept=".pdf,.docx" required onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
          <select value={category} onChange={(e) => setCategory(e.target.value)}>
            <option value="cv">CV / Resume</option>
            <option value="certificate">Certificate</option>
            <option value="academic">Academic Transcript</option>
            <option value="portfolio">Portfolio</option>
            <option value="other">Other</option>
          </select>
          <label className="checkbox-inline">
            <input type="checkbox" checked={isDefault} onChange={(e) => setIsDefault(e.target.checked)} />
            <span>Set as default CV</span>
          </label>
          <button type="submit" className="btn btn-primary" disabled={!file}>
            <Upload size={15} /> Upload
          </button>
        </form>
      </section>

      <div className="grid-2">
        <section className="card">
          <h3>Stored Documents</h3>
          {docs.length === 0 ? (
            <div className="empty-state">No documents uploaded yet.</div>
          ) : (
            <div className="stack-sm">
              {docs.map((doc) => (
                <div key={doc.id} className="list-row">
                  <div>
                    <strong>{doc.name}</strong>
                    <div className="muted small">
                      {doc.category} {doc.is_default ? '· Default CV' : ''}
                    </div>
                  </div>
                  <div className="actions-cell">
                    <button type="button" className="btn btn-secondary btn-sm" onClick={() => void handlePreview(doc)}>
                      <Eye size={13} /> Preview
                    </button>
                    {doc.category === 'cv' && !doc.is_default && (
                      <button
                        type="button"
                        className="btn btn-secondary btn-sm"
                        onClick={() => void api.setDefaultCv(doc.id).then(() => load())}
                      >
                        Set Default
                      </button>
                    )}
                    <a
                      className="btn btn-ghost btn-sm"
                      href={`${import.meta.env.VITE_API_BASE_URL ?? '/api'}/documents/${doc.id}/download`}
                      aria-label={`Download ${doc.name}`}
                    >
                      <Download size={14} />
                    </a>
                    <button
                      type="button"
                      className="btn btn-ghost btn-sm"
                      onClick={() => void api.deleteDocument(doc.id).then(() => load())}
                      aria-label={`Delete ${doc.name}`}
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>

        <section className="card">
          <h3>Document Text Preview {previewTitle ? `— ${previewTitle}` : ''}</h3>
          <pre className="preview-pre">{previewText ?? 'Select a document to preview extracted text.'}</pre>
        </section>
      </div>
    </div>
  );
}

export function ProfilePage({ onNotify }: { onNotify: (msg: string, isError?: boolean) => void }) {
  const [profile, setProfile] = useState<ProfileData | null>(null);
  const [facts, setFacts] = useState<ProfileFactItem[]>([]);
  const [phone, setPhone] = useState('');
  const [city, setCity] = useState('');
  const [country, setCountry] = useState('');
  const [linkedin, setLinkedin] = useState('');
  const [summary, setSummary] = useState('');
  const [skillName, setSkillName] = useState('');
  const [expCompany, setExpCompany] = useState('');
  const [expTitle, setExpTitle] = useState('');
  const [eduInst, setEduInst] = useState('');
  const [eduQual, setEduQual] = useState('');

  const load = useCallback(async () => {
    try {
      const [p, f] = await Promise.all([api.getProfile(), api.getProfileFacts()]);
      setProfile(p);
      setFacts(f);
      setPhone(p.personal.phone || '');
      setCity(p.personal.city || '');
      setCountry(p.personal.country || '');
      setLinkedin(p.personal.linkedin_url || '');
      setSummary(p.personal.professional_summary || '');
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'Failed to load profile', true);
    }
  }, [onNotify]);

  useEffect(() => {
    void load();
  }, [load]);

  async function savePersonal(e: FormEvent) {
    e.preventDefault();
    try {
      await api.updateProfile({
        phone: phone || null,
        city: city || null,
        country: country || null,
        linkedin_url: linkedin || null,
        professional_summary: summary || null,
      });
      onNotify('Career profile updated');
      await load();
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'Profile update failed', true);
    }
  }

  if (!profile) return <div className="card empty-state">Loading career profile...</div>;

  return (
    <div className="stack-lg">
      <section className="card">
        <div className="card-header">
          <div>
            <h3>Profile Completeness</h3>
            <p className="muted small">Verified profile facts prevent fabricated claims in generated CVs and forms.</p>
          </div>
          <span className="pill pill-success">{profile.completeness_score}%</span>
        </div>
        <div className="progress-track">
          <div className="progress-fill" style={{ width: `${profile.completeness_score}%` }} />
        </div>
      </section>

      <section className="card">
        <h3>Personal &amp; Summary</h3>
        <form onSubmit={savePersonal} className="stack">
          <div className="grid-2">
            <label className="field"><span>Phone</span><input value={phone} onChange={(e) => setPhone(e.target.value)} /></label>
            <label className="field"><span>City</span><input value={city} onChange={(e) => setCity(e.target.value)} /></label>
            <label className="field"><span>Country</span><input value={country} onChange={(e) => setCountry(e.target.value)} /></label>
            <label className="field"><span>LinkedIn URL</span><input value={linkedin} onChange={(e) => setLinkedin(e.target.value)} placeholder="https://linkedin.com/in/..." /></label>
          </div>
          <label className="field"><span>Professional Summary</span><textarea rows={3} value={summary} onChange={(e) => setSummary(e.target.value)} /></label>
          <div>
            <button type="submit" className="btn btn-primary">Save Personal Profile</button>
          </div>
        </form>
      </section>

      <div className="grid-2">
        <section className="card">
          <h3>Skills ({profile.skills.length})</h3>
          <form
            onSubmit={async (e) => {
              e.preventDefault();
              if (!skillName.trim()) return;
              await api.addSkill({ name: skillName.trim(), category: 'technical', years_experience: 2 });
              setSkillName('');
              await load();
            }}
            className="inline-form"
          >
            <input value={skillName} onChange={(e) => setSkillName(e.target.value)} placeholder="Add skill (e.g. Python)" />
            <button type="submit" className="btn btn-secondary">Add</button>
          </form>
          <div className="tag-list" style={{ marginTop: 12 }}>
            {profile.skills.map((s) => (
              <span key={s.id} className="pill pill-neutral">
                {s.name}
                <button type="button" className="pill-x" onClick={() => void api.deleteSkill(s.id).then(() => load())} aria-label={`Remove ${s.name}`}>×</button>
              </span>
            ))}
          </div>
        </section>

        <section className="card">
          <h3>Verified &amp; Suggested Facts</h3>
          {facts.length === 0 ? (
            <p className="muted small">No facts recorded yet.</p>
          ) : (
            <div className="stack-sm">
              {facts.slice(0, 6).map((fact) => (
                <div key={fact.id} className="list-row">
                  <div>
                    <strong>{fact.field_key}</strong>
                    <div className="muted small">{fact.value.slice(0, 80)}</div>
                  </div>
                  {fact.status === 'confirmed' ? (
                    <span className="pill pill-success">Confirmed</span>
                  ) : (
                    <button type="button" className="btn btn-secondary btn-sm" onClick={() => void api.confirmProfileFact(fact.id).then(() => load())}>
                      <Check size={13} /> Confirm
                    </button>
                  )}
                </div>
              ))}
            </div>
          )}
        </section>
      </div>

      <div className="grid-2">
        <section className="card">
          <h3>Experience</h3>
          <form
            onSubmit={async (e) => {
              e.preventDefault();
              if (!expCompany.trim() || !expTitle.trim()) return;
              await api.addExperience({ company: expCompany.trim(), title: expTitle.trim() });
              setExpCompany('');
              setExpTitle('');
              await load();
            }}
            className="inline-form"
          >
            <input value={expCompany} onChange={(e) => setExpCompany(e.target.value)} placeholder="Company" />
            <input value={expTitle} onChange={(e) => setExpTitle(e.target.value)} placeholder="Title" />
            <button type="submit" className="btn btn-secondary">Add</button>
          </form>
          <div className="stack-sm" style={{ marginTop: 12 }}>
            {profile.experience.map((item) => (
              <div key={item.id} className="list-row">
                <span><strong>{item.title}</strong> · {item.company}</span>
                <button type="button" className="btn btn-ghost btn-sm" onClick={() => void api.deleteExperience(item.id).then(() => load())}><Trash2 size={14} /></button>
              </div>
            ))}
          </div>
        </section>

        <section className="card">
          <h3>Education</h3>
          <form
            onSubmit={async (e) => {
              e.preventDefault();
              if (!eduInst.trim()) return;
              await api.addEducation({ institution: eduInst.trim(), qualification: eduQual.trim() || null });
              setEduInst('');
              setEduQual('');
              await load();
            }}
            className="inline-form"
          >
            <input value={eduInst} onChange={(e) => setEduInst(e.target.value)} placeholder="Institution" />
            <input value={eduQual} onChange={(e) => setEduQual(e.target.value)} placeholder="Qualification" />
            <button type="submit" className="btn btn-secondary">Add</button>
          </form>
          <div className="stack-sm" style={{ marginTop: 12 }}>
            {profile.education.map((item) => (
              <div key={item.id} className="list-row">
                <span><strong>{item.institution}</strong> {item.qualification ? `· ${item.qualification}` : ''}</span>
                <button type="button" className="btn btn-ghost btn-sm" onClick={() => void api.deleteEducation(item.id).then(() => load())}><Trash2 size={14} /></button>
              </div>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}
