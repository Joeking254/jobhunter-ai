import '@testing-library/jest-dom/vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import App, { NAV_ITEMS } from './App';

function jsonResponse(data: unknown, status = 200) {
  return Promise.resolve(
    new Response(status === 204 ? null : JSON.stringify(data), {
      status,
      headers: status === 204 ? {} : { 'Content-Type': 'application/json' },
    })
  );
}

describe('JOBHUNTER AI Professional Dashboard', () => {
  const fetchCalls: { url: string; method: string; body?: string }[] = [];

  beforeEach(() => {
    fetchCalls.length = 0;
    window.localStorage.clear();
    document.cookie = 'jobhunter_csrf=test-csrf-token; path=/';

    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        const method = (init?.method ?? 'GET').toUpperCase();
        fetchCalls.push({ url, method, body: typeof init?.body === 'string' ? init.body : undefined });

        if (url.endsWith('/api/auth/me')) {
          return jsonResponse({ id: 'u1', email: 'ada@example.com', first_name: 'Ada', last_name: 'Lovelace', is_admin: true, is_verified: true });
        }
        if (url.endsWith('/api/sources')) {
          return jsonResponse([
            { id: 's1', name: 'Remotive', base_url: 'https://remotive.com', connector_type: 'remotive', is_active: true, reliability_score: 98, last_success_at: null, automation_permitted: true },
          ]);
        }
        if (url.endsWith('/api/dashboard/overview')) {
          return jsonResponse({
            total_opportunities: 42,
            new_opportunities: 9,
            strong_matches: 7,
            recommended_matches: 15,
            pending_approvals: 3,
            applications_submitted: 11,
            interview_invitations: 4,
            rejected_applications: 2,
            failed_applications: 1,
            confirmation_pending: 1,
            success_statistics: { submission_success_rate_pct: 84.6, interview_conversion_rate_pct: 36.4, approval_rate_pct: 85.7, total_applications: 18 },
            status_breakdown: { submitted: 11, pending_approval: 3, rejected: 2 },
          });
        }
        if (url.includes('/api/opportunities/discovery-history')) {
          return jsonResponse([
            { id: 'h1', source_id: 's1', source_name: 'Remotive', status: 'success', started_at: '2026-11-26T10:00:00Z', finished_at: '2026-11-26T10:01:00Z', fetched_count: 15, created_count: 4, updated_count: 2, error_message: null },
          ]);
        }
        if (url.includes('/api/opportunities?')) {
          return jsonResponse({
            items: [
              {
                id: 'opp1',
                source_id: 's1',
                source_name: 'Remotive',
                title: 'Backend Python Engineer',
                company: 'Acme Cloud',
                location: 'Remote',
                url: 'https://acme.test/1',
                description: 'FastAPI role',
                posted_at: '2026-11-25T10:00:00Z',
                deadline: '2026-12-15T00:00:00Z',
                salary_text: '$110k',
                salary_min: 100000,
                salary_max: 110000,
                salary_currency: 'USD',
                remote_only: true,
                categories: 'software_development',
                expired_at: null,
                match_score: 91,
                eligible: true,
                risk_level: 'low',
                match_explanation: 'Matched Python and FastAPI',
                missing_skills: [],
                matching_skills: ['python'],
                risk_warnings: [],
                recommended_next_action: 'Apply',
                application_id: null,
                application_status: 'discovered',
              },
            ],
            total: 25,
            page: 1,
            page_size: 10,
            total_pages: 3,
          });
        }
        if (url.endsWith('/api/applications/queue')) {
          return jsonResponse([
            {
              id: 'app1',
              opportunity_id: 'opp2',
              status: 'pending_approval',
              application_url: 'https://beta.test/apply',
              title: 'ML Engineer',
              company: 'Beta AI',
              job: { id: 'opp2', title: 'ML Engineer', company: 'Beta AI', location: 'Nairobi', url: 'https://beta.test/apply', description: 'Build ML pipelines', deadline: null, salary_text: '$95k', remote_only: false },
              match_score: 78,
              match_explanation: 'Strong Python skills; missing Kubernetes.',
              missing_qualifications: ['kubernetes'],
              eligibility_warnings: ['Source does not permit automated submission.'],
              cv_document_id: 'doc-cv',
              cv_preview: 'Ada Lovelace CV Preview Text',
              cover_letter_document_id: 'doc-cl',
              cover_letter_preview: 'Dear Beta AI Hiring Team...',
              answers: { 'Why Beta AI?': 'Excited about ML systems.' },
              confirmation_reference: null,
              last_error: null,
              requires_manual_intervention: false,
              source_permits_automation: false,
              required_documents_verified: true,
              required_answers_verified: true,
              sensitive_declarations_verified: true,
              prepared_at: '2026-11-26T09:00:00Z',
              submitted_at: null,
            },
          ]);
        }
        if (url.endsWith('/api/applications/app1/approve')) return jsonResponse({ status: 'approved' });
        if (url.endsWith('/api/applications/app1/reject')) return jsonResponse({ status: 'rejected' });
        if (url.includes('/api/applications')) {
          return jsonResponse({
            items: [
              { id: 'app-sub', opportunity_id: 'opp1', status: 'submitted', application_url: 'https://acme.test/1', title: 'Backend Python Engineer', company: 'Acme Cloud', job: null, match_score: 91, match_explanation: null, missing_qualifications: [], eligibility_warnings: [], cv_document_id: null, cv_preview: null, cover_letter_document_id: null, cover_letter_preview: null, answers: {}, confirmation_reference: 'CONF-101', last_error: null, requires_manual_intervention: false, source_permits_automation: true, required_documents_verified: true, required_answers_verified: true, sensitive_declarations_verified: true, prepared_at: null, submitted_at: '2026-11-26T12:00:00Z' },
            ],
            counts: { total: 1, submitted: 1, prepared_not_submitted: 0, by_status: { submitted: 1 } },
          });
        }
        if (url.endsWith('/api/interviews')) {
          return jsonResponse([{ id: 'iv1', application_id: 'app-sub', scheduled_at: '2026-12-01T14:00:00Z', interview_type: 'Technical', notes: 'Zoom link', title: 'Backend Python Engineer', company: 'Acme Cloud', application_status: 'submitted' }]);
        }
        if (url.endsWith('/api/documents')) {
          return jsonResponse([{ id: 'd1', name: 'ada-cv.pdf', category: 'cv', mime_type: 'application/pdf', size_bytes: 2048, is_default: true, created_at: '2026-11-26T08:00:00Z' }]);
        }
        if (url.endsWith('/api/profile')) {
          return jsonResponse({
            personal: { first_name: 'Ada', last_name: 'Lovelace', email: 'ada@example.com', phone: '+254700000000', country: 'Kenya', city: 'Nairobi', professional_summary: 'Software Engineer', portfolio_links: [], linkedin_url: null },
            education: [{ id: 'ed1', institution: 'University', qualification: 'BSc', field_of_study: 'CS', current_status: 'completed' }],
            experience: [{ id: 'ex1', company: 'Analytical Engines', title: 'Engineer', employment_type: 'full_time', achievements: null }],
            skills: [{ id: 'sk1', name: 'Python', category: 'programming', proficiency: 'advanced', years_experience: 5 }],
            completeness_score: 88,
          });
        }
        if (url.endsWith('/api/profile/facts')) return jsonResponse([]);
        if (url.endsWith('/api/saved-searches')) {
          return jsonResponse([{ id: 'ss1', name: 'Remote Python', query: 'python', filters: { remote_only: true }, is_active: true, created_at: '2026-11-25T10:00:00Z' }]);
        }
        if (url.endsWith('/api/dashboard/ai-config')) {
          return jsonResponse({
            ai_provider: 'rules',
            ai_model: 'configured-model',
            thresholds: { strong_match: 85, approval_required: 65 },
            weights: { skills: 35, education: 15, experience: 20, location: 10, authorization: 10, type: 5, preference: 5 },
            preferences: { work_authorization: 'Kenya', preferred_locations: 'Nairobi, Remote', remote_only: true, opportunity_types: 'full-time', career_preferences: 'Backend Engineer' },
          });
        }
        if (url.endsWith('/api/bot/status')) {
          return jsonResponse({
            config: { bot_paused: false, auto_apply_paused: false, search_frequency_minutes: 360, match_strong_threshold: 85, match_approval_threshold: 65, last_discovery_at: null, last_analytics_at: null },
            health: { redis_status: 'ok', shutting_down: false, workers: [], last_db_heartbeat_at: null, queue_depths: { celery: 0, discovery: 0, analysis: 0, applications: 0, notifications: 0, maintenance: 0 }, active_tasks: [] },
            recent_runs: [],
          });
        }
        if (url.endsWith('/api/notifications/settings')) {
          return jsonResponse({
            telegram_enabled: true,
            telegram_chat_id: '987654321',
            email_notifications_enabled: true,
            notification_frequency: 'immediate',
            min_notification_match_score: 75,
            categories: { telegram: { strong_match: true }, email: { weekly_summary: true } },
          });
        }
        if (url.endsWith('/api/notifications/deliveries')) return jsonResponse([]);
        if (url.endsWith('/api/dashboard/analytics')) {
          return jsonResponse({
            opportunities_by_week: [{ week: '2026-W47', count: 18 }, { week: '2026-W48', count: 24 }],
            applications_submitted: [{ week: '2026-W47', count: 5 }, { week: '2026-W48', count: 6 }],
            applications_by_category: [{ category: 'software_development', count: 10 }],
            interview_conversion: { matched: 30, prepared: 16, submitted: 11, interviews: 4, conversion_rate_pct: 36.4 },
            source_performance: [{ source_id: 's1', name: 'Remotive', reliability_score: 98, opportunities: 42, strong_matches: 7, applications: 16, submitted: 11 }],
            match_distribution: [{ range: '0-39', count: 4 }, { range: '40-64', count: 6 }, { range: '65-84', count: 13 }, { range: '85-100', count: 7 }],
          });
        }
        if (url.endsWith('/api/auth/account')) {
          return jsonResponse({
            id: 'u1',
            email: 'ada@example.com',
            first_name: 'Ada',
            last_name: 'Lovelace',
            is_admin: true,
            is_verified: true,
            last_login_at: null,
            timezone: 'Africa/Nairobi',
            locale: 'en',
            active_sessions: [{ id: 'ses1', ip_address: '127.0.0.1', user_agent: 'Vitest', created_at: '2026-11-26T00:00:00Z', expires_at: '2026-12-03T00:00:00Z' }],
          });
        }
        return jsonResponse({});
      })
    );
  });

  it('renders live overview data and navigates across all 15 dashboard pages', async () => {
    render(<App />);

    await waitFor(() => expect(screen.getByText('42')).toBeInTheDocument());
    expect(screen.getByText('Total Opportunities Discovered')).toBeInTheDocument();
    expect(screen.getAllByText('84.6%').length).toBeGreaterThanOrEqual(1);

    // Verify all 15 required navigation items exist and navigate cleanly
    expect(NAV_ITEMS).toHaveLength(15);
    for (const item of NAV_ITEMS) {
      fireEvent.click(screen.getByRole('button', { name: item.label }));
      await waitFor(() => expect(screen.getByRole('heading', { level: 1, name: item.label })).toBeInTheDocument());
    }
  }, 15000);

  it('supports theme switching and responsive mobile drawer navigation', async () => {
    render(<App />);
    await waitFor(() => expect(screen.getByText('42')).toBeInTheDocument());

    expect(document.documentElement.getAttribute('data-theme')).toBe('dark');
    fireEvent.click(screen.getByRole('button', { name: 'Toggle color theme' }));
    expect(document.documentElement.getAttribute('data-theme')).toBe('light');

    const sidebar = screen.getByLabelText('Sidebar navigation');
    fireEvent.click(screen.getByRole('button', { name: 'Open navigation menu' }));
    expect(sidebar.className).toContain('open');
    fireEvent.click(screen.getByRole('button', { name: 'Analytics' }));
    expect(sidebar.className).not.toContain('open');
  });

  it('filters, sorts, and paginates job listings and handles approval queue actions', async () => {
    render(<App />);
    await waitFor(() => expect(screen.getByText('42')).toBeInTheDocument());

    // Job listings search, sort, pagination
    fireEvent.click(screen.getByRole('button', { name: 'All Opportunities' }));
    await waitFor(() => expect(screen.getByText('Backend Python Engineer')).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText('Search opportunities'), { target: { value: 'Python' } });
    fireEvent.change(screen.getByLabelText('Sort opportunities'), { target: { value: 'deadline' } });
    const nextBtn = await screen.findByRole('button', { name: 'Next' });
    fireEvent.click(nextBtn);
    await waitFor(() => expect(fetchCalls.some((c) => c.url.includes('q=Python') && c.url.includes('sort_by=deadline') && c.url.includes('page=2'))).toBe(true));

    // Approval queue previews & actions
    fireEvent.click(screen.getByRole('button', { name: 'Pending Approvals' }));
    await waitFor(() => expect(screen.getByText('Build ML pipelines')).toBeInTheDocument());
    expect(screen.getByText('Strong Python skills; missing Kubernetes.')).toBeInTheDocument();
    expect(screen.getByText('kubernetes')).toBeInTheDocument();
    expect(screen.getByText('Source does not permit automated submission.')).toBeInTheDocument();
    expect(screen.getByDisplayValue('Ada Lovelace CV Preview Text')).toBeInTheDocument();
    expect(screen.getByDisplayValue('Dear Beta AI Hiring Team...')).toBeInTheDocument();
    expect(screen.getByDisplayValue('Excited about ML systems.')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Approve' }));
    await waitFor(() => expect(fetchCalls.some((c) => c.url.endsWith('/api/applications/app1/approve') && c.method === 'POST')).toBe(true));

    // Analytics renders all 6 chart sections
    fireEvent.click(screen.getByRole('button', { name: 'Analytics' }));
    await waitFor(() => expect(screen.getByText('Opportunities discovered by week')).toBeInTheDocument());
    expect(screen.getByText('Applications submitted')).toBeInTheDocument();
    expect(screen.getByText('Applications by category')).toBeInTheDocument();
    expect(screen.getByText('Interview conversion')).toBeInTheDocument();
    expect(screen.getByText('Source performance')).toBeInTheDocument();
    expect(screen.getByText('Match distribution')).toBeInTheDocument();

    // Bot controls on AI Configuration page
    fireEvent.click(screen.getByRole('button', { name: 'AI Configuration' }));
    await waitFor(() => expect(screen.getByText(/Autonomous Bot/i)).toBeInTheDocument());
    expect(screen.getByRole('button', { name: 'Pause Bot' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Pause Auto-Apply' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Start Manual Search' })).toBeInTheDocument();
    expect(screen.getByLabelText('Search frequency')).toBeInTheDocument();
  }, 10000);
});
