import { useCallback, useEffect, useState } from 'react';
import { AlertTriangle, CheckCircle2, Save, Send, XCircle } from 'lucide-react';
import { api, type ApplicationReviewItem } from '../api/client';

export function ApprovalQueueView({
  onNotify,
  onChanged,
}: {
  onNotify: (msg: string, isError?: boolean) => void;
  onChanged: () => void;
}) {
  const [items, setItems] = useState<ApplicationReviewItem[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [rejectReason, setRejectReason] = useState('Not aligned with target role');
  const [cvDraft, setCvDraft] = useState('');
  const [coverDraft, setCoverDraft] = useState('');
  const [answersDraft, setAnswersDraft] = useState<Record<string, string>>({});

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const queue = await api.getApprovalQueue();
      setItems(queue);
      if (queue.length > 0) {
        const current = queue.find((item) => item.id === selectedId) ?? queue[0];
        setSelectedId(current.id);
        setCvDraft(current.cv_preview ?? '');
        setCoverDraft(current.cover_letter_preview ?? '');
        setAnswersDraft(current.answers ?? {});
      } else {
        setSelectedId(null);
      }
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'Failed to load approval queue', true);
    } finally {
      setLoading(false);
    }
  }, [onNotify, selectedId]);

  useEffect(() => {
    void load();
  }, [load]);

  const selected = items.find((item) => item.id === selectedId) ?? null;

  function selectItem(item: ApplicationReviewItem) {
    setSelectedId(item.id);
    setCvDraft(item.cv_preview ?? '');
    setCoverDraft(item.cover_letter_preview ?? '');
    setAnswersDraft(item.answers ?? {});
  }

  async function handleSaveEdits() {
    if (!selected) return;
    setBusy(true);
    try {
      await api.editApplication(selected.id, {
        answers: answersDraft,
        cv_text: cvDraft || undefined,
        cover_letter_text: coverDraft || undefined,
      });
      onNotify('Saved application edits');
      await load();
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'Failed to save edits', true);
    } finally {
      setBusy(false);
    }
  }

  async function handleApprove(andSubmit = false) {
    if (!selected) return;
    setBusy(true);
    try {
      await api.approveApplication(selected.id);
      if (andSubmit) {
        const res = await api.submitApplication(selected.id);
        onNotify(`Application ${res.status}${res.confirmation_reference ? ` (${res.confirmation_reference})` : ''}`);
      } else {
        onNotify(`Approved application for ${selected.title}`);
      }
      onChanged();
      await load();
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'Approval action failed', true);
    } finally {
      setBusy(false);
    }
  }

  async function handleReject() {
    if (!selected) return;
    setBusy(true);
    try {
      await api.rejectApplication(selected.id, rejectReason.trim() || 'Rejected by owner');
      onNotify(`Rejected application for ${selected.title}`);
      onChanged();
      await load();
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'Rejection failed', true);
    } finally {
      setBusy(false);
    }
  }

  if (loading) return <div className="card empty-state">Loading approval queue...</div>;
  if (items.length === 0) return <div className="card empty-state">No applications are waiting for approval.</div>;

  return (
    <div className="split-layout">
      <aside className="card queue-list" aria-label="Pending approval items">
        <h3>Queue ({items.length})</h3>
        <div className="stack-sm">
          {items.map((item) => (
            <button
              key={item.id}
              type="button"
              className={`queue-item ${item.id === selected?.id ? 'active' : ''}`}
              onClick={() => selectItem(item)}
            >
              <div className="queue-item-head">
                <strong>{item.title || 'Untitled role'}</strong>
                <span className="pill pill-warning">{item.match_score ?? '—'}%</span>
              </div>
              <span className="muted small">{item.company || 'Unknown employer'}</span>
            </button>
          ))}
        </div>
      </aside>

      {selected && (
        <div className="stack">
          <section className="card">
            <div className="card-header">
              <div>
                <h2>{selected.job?.title || selected.title}</h2>
                <p className="muted">
                  {selected.job?.company || selected.company}
                  {selected.job?.location ? ` · ${selected.job.location}` : ''}
                  {selected.job?.salary_text ? ` · ${selected.job.salary_text}` : ''}
                </p>
              </div>
              <span className="pill pill-warning">Match {selected.match_score ?? '—'}%</span>
            </div>

            <div className="stack">
              <div>
                <h4>Job Description</h4>
                <p className="description-box">{selected.job?.description || 'No description provided.'}</p>
              </div>

              <div className="grid-2">
                <div className="subcard">
                  <h4>Match Explanation</h4>
                  <p className="small">{selected.match_explanation || 'No match explanation recorded.'}</p>
                </div>
                <div className="subcard">
                  <h4>Missing Qualifications</h4>
                  {selected.missing_qualifications.length === 0 ? (
                    <p className="small muted">No missing qualifications detected.</p>
                  ) : (
                    <div className="tag-list">
                      {selected.missing_qualifications.map((skill) => (
                        <span key={skill} className="pill pill-neutral">
                          {skill}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              </div>

              {selected.eligibility_warnings.length > 0 && (
                <div className="alert alert-warning">
                  <AlertTriangle size={16} />
                  <div>
                    <strong>Eligibility &amp; Compliance Warnings</strong>
                    <ul className="compact-list">
                      {selected.eligibility_warnings.map((w) => (
                        <li key={w}>{w}</li>
                      ))}
                    </ul>
                  </div>
                </div>
              )}
            </div>
          </section>

          <section className="card">
            <h3>Generated Documents &amp; Application Answers</h3>
            <div className="grid-2">
              <label className="field">
                <span>Generated CV Preview</span>
                <textarea rows={9} value={cvDraft} onChange={(e) => setCvDraft(e.target.value)} />
              </label>
              <label className="field">
                <span>Cover Letter Preview</span>
                <textarea rows={9} value={coverDraft} onChange={(e) => setCoverDraft(e.target.value)} />
              </label>
            </div>

            <div className="stack-sm" style={{ marginTop: 16 }}>
              <h4>Application Answers</h4>
              {Object.keys(answersDraft).length === 0 ? (
                <p className="small muted">No custom questions recorded for this application.</p>
              ) : (
                Object.entries(answersDraft).map(([question, answer]) => (
                  <label key={question} className="field">
                    <span>{question}</span>
                    <input
                      value={answer}
                      onChange={(e) => setAnswersDraft((prev) => ({ ...prev, [question]: e.target.value }))}
                    />
                  </label>
                ))
              )}
            </div>

            <div className="approval-actions">
              <button type="button" className="btn btn-secondary" disabled={busy} onClick={() => void handleSaveEdits()}>
                <Save size={15} /> Save Edits
              </button>
              <button type="button" className="btn btn-primary" disabled={busy} onClick={() => void handleApprove(false)}>
                <CheckCircle2 size={15} /> Approve
              </button>
              <button type="button" className="btn btn-success" disabled={busy} onClick={() => void handleApprove(true)}>
                <Send size={15} /> Approve &amp; Submit
              </button>
              <div className="inline-row reject-box">
                <input
                  aria-label="Rejection reason"
                  value={rejectReason}
                  onChange={(e) => setRejectReason(e.target.value)}
                  placeholder="Rejection reason"
                />
                <button type="button" className="btn btn-danger" disabled={busy} onClick={() => void handleReject()}>
                  <XCircle size={15} /> Reject
                </button>
              </div>
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
