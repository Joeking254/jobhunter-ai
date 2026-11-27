export interface User {
  id: string;
  email: string;
  first_name: string;
  last_name: string;
  is_admin: boolean;
  is_verified: boolean;
}

export interface OverviewData {
  total_opportunities: number;
  new_opportunities: number;
  strong_matches: number;
  recommended_matches: number;
  pending_approvals: number;
  applications_submitted: number;
  interview_invitations: number;
  rejected_applications: number;
  failed_applications: number;
  confirmation_pending: number;
  success_statistics: {
    submission_success_rate_pct: number;
    interview_conversion_rate_pct: number;
    approval_rate_pct: number;
    total_applications: number;
  };
  status_breakdown: Record<string, number>;
}

export interface OpportunityItem {
  id: string;
  source_id: string;
  source_name: string | null;
  title: string;
  company: string;
  location: string | null;
  url: string;
  description: string | null;
  posted_at: string | null;
  deadline: string | null;
  salary_text: string | null;
  salary_min: number | null;
  salary_max: number | null;
  salary_currency: string | null;
  remote_only: boolean;
  categories: string | null;
  expired_at: string | null;
  match_score: number | null;
  eligible: boolean | null;
  risk_level: string | null;
  match_explanation: string | null;
  missing_skills: string[];
  matching_skills: string[];
  risk_warnings: string[];
  recommended_next_action: string | null;
  application_id: string | null;
  application_status: string;
}

export interface OpportunitiesResponse {
  items: OpportunityItem[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export interface DiscoveryHistoryItem {
  id: string;
  source_id: string;
  source_name: string;
  status: string;
  started_at: string;
  finished_at: string | null;
  fetched_count: number;
  created_count: number;
  updated_count: number;
  error_message: string | null;
}

export interface ApplicationReviewItem {
  id: string;
  opportunity_id: string;
  status: string;
  application_url: string | null;
  title: string | null;
  company: string | null;
  job: {
    id: string;
    title: string;
    company: string;
    location: string | null;
    url: string;
    description: string | null;
    deadline: string | null;
    salary_text: string | null;
    remote_only: boolean;
  } | null;
  match_score: number | null;
  match_explanation: string | null;
  missing_qualifications: string[];
  eligibility_warnings: string[];
  cv_document_id: string | null;
  cv_preview: string | null;
  cover_letter_document_id: string | null;
  cover_letter_preview: string | null;
  answers: Record<string, string>;
  confirmation_reference: string | null;
  last_error: string | null;
  requires_manual_intervention: boolean;
  source_permits_automation: boolean;
  required_documents_verified: boolean;
  required_answers_verified: boolean;
  sensitive_declarations_verified: boolean;
  prepared_at: string | null;
  submitted_at: string | null;
}

export interface ApplicationsListResponse {
  items: ApplicationReviewItem[];
  counts: {
    total: number;
    submitted: number;
    prepared_not_submitted: number;
    by_status: Record<string, number>;
  };
}

export interface AnalyticsData {
  opportunities_by_week: { week: string; count: number }[];
  applications_submitted: { week: string; count: number }[];
  applications_by_category: { category: string; count: number }[];
  interview_conversion: {
    matched: number;
    prepared: number;
    submitted: number;
    interviews: number;
    conversion_rate_pct: number;
  };
  source_performance: {
    source_id: string;
    name: string;
    reliability_score: number;
    opportunities: number;
    strong_matches: number;
    applications: number;
    submitted: number;
  }[];
  match_distribution: { range: string; count: number }[];
}

export interface InterviewItem {
  id: string;
  application_id: string;
  scheduled_at: string;
  interview_type: string | null;
  notes: string | null;
  title: string | null;
  company: string | null;
  application_status: string | null;
}

export interface DocumentItem {
  id: string;
  name: string;
  category: string;
  mime_type: string | null;
  size_bytes: number | null;
  is_default: boolean;
  created_at: string;
}

export interface ProfileData {
  personal: {
    first_name: string;
    last_name: string;
    email: string;
    phone: string | null;
    country: string | null;
    city: string | null;
    professional_summary: string | null;
    portfolio_links: string[];
    linkedin_url: string | null;
  };
  education: { id: string; institution: string; qualification: string | null; field_of_study: string | null; current_status: string | null }[];
  experience: { id: string; company: string; title: string; employment_type: string | null; achievements: string | null }[];
  skills: { id: string; name: string; category: string; proficiency: string | null; years_experience: number | null }[];
  completeness_score: number;
}

export interface ProfileFactItem {
  id: string;
  field_key: string;
  value: string;
  status: string;
  source: string;
}

export interface JobSourceItem {
  id: string;
  name: string;
  base_url: string;
  connector_type: string;
  is_active: boolean;
  reliability_score: number;
  last_success_at: string | null;
  automation_permitted: boolean;
}

export interface SavedSearchItem {
  id: string;
  name: string;
  query: string | null;
  filters: Record<string, unknown>;
  is_active: boolean;
  created_at: string;
}

export interface AIConfigData {
  ai_provider: string;
  ai_model: string;
  thresholds: { strong_match: number; approval_required: number };
  weights: Record<string, number>;
  preferences: {
    work_authorization: string | null;
    preferred_locations: string | null;
    remote_only: boolean;
    opportunity_types: string | null;
    career_preferences: string | null;
  };
}

export interface NotificationSettingsData {
  telegram_enabled: boolean;
  telegram_chat_id: string | null;
  email_notifications_enabled: boolean;
  notification_frequency: string;
  min_notification_match_score: number;
  categories: Record<string, Record<string, boolean>>;
}

export interface NotificationDeliveryItem {
  id: string;
  channel: string;
  event_type: string;
  status: string;
  attempts: number;
  max_attempts: number;
  last_error: string | null;
  sent_at: string | null;
}

export interface AccountData {
  id: string;
  email: string;
  first_name: string;
  last_name: string;
  is_admin: boolean;
  is_verified: boolean;
  last_login_at: string | null;
  timezone: string;
  locale: string;
  active_sessions: { id: string; ip_address: string | null; user_agent: string | null; created_at: string; expires_at: string }[];
}

export interface BotStatusData {
  config: {
    bot_paused: boolean;
    auto_apply_paused: boolean;
    search_frequency_minutes: number;
    match_strong_threshold: number;
    match_approval_threshold: number;
    last_discovery_at: string | null;
    last_analytics_at: string | null;
  };
  health: {
    redis_status: string;
    shutting_down: boolean;
    workers: { worker_id: string; queues: string[]; timestamp: string }[];
    last_db_heartbeat_at: string | null;
    queue_depths: Record<string, number>;
    active_tasks: { id: string; bot_name: string; queue_name: string; started_at: string }[];
  };
  recent_runs: {
    id: string;
    bot_name: string;
    queue_name: string;
    status: string;
    attempt: number;
    duration_ms: number | null;
    started_at: string | null;
    finished_at: string | null;
    error_message: string | null;
  }[];
}

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '/api';

function getCookie(name: string): string {
  const escaped = name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const match = document.cookie.match(new RegExp(`(?:^|; )${escaped}=([^;]*)`));
  return match ? decodeURIComponent(match[1]) : '';
}

export async function apiRequest<T>(path: string, options: RequestInit = {}): Promise<T> {
  const method = (options.method ?? 'GET').toUpperCase();
  const headers = new Headers(options.headers);
  if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) {
    const csrf = getCookie('jobhunter_csrf');
    if (csrf) headers.set('X-CSRF-Token', csrf);
  }
  if (options.body && !(options.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers,
    credentials: 'include',
  });
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      const data = await response.json();
      if (data?.detail) message = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail);
    } catch {
      // ignore parse failure
    }
    throw new Error(message);
  }
  if (response.status === 204) return undefined as T;
  const contentType = response.headers.get('content-type') || '';
  if (contentType.includes('application/json')) return (await response.json()) as T;
  return (await response.text()) as T;
}

export const api = {
  me: () => apiRequest<User>('/auth/me'),
  login: (email: string, password: string) => apiRequest<User>('/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) }),
  register: (payload: { email: string; password: string; first_name: string; last_name: string }) =>
    apiRequest<User>('/auth/register', { method: 'POST', body: JSON.stringify(payload) }),
  logout: () => apiRequest<void>('/auth/logout', { method: 'POST' }),
  getAccount: () => apiRequest<AccountData>('/auth/account'),
  updateAccount: (payload: { first_name?: string; last_name?: string; timezone?: string; locale?: string }) =>
    apiRequest<AccountData>('/auth/account', { method: 'PUT', body: JSON.stringify(payload) }),
  changePassword: (current_password: string, new_password: string) =>
    apiRequest<{ status: string }>('/auth/change-password', { method: 'POST', body: JSON.stringify({ current_password, new_password }) }),

  getOverview: () => apiRequest<OverviewData>('/dashboard/overview'),
  getAnalytics: () => apiRequest<AnalyticsData>('/dashboard/analytics'),
  getAIConfig: () => apiRequest<AIConfigData>('/dashboard/ai-config'),
  updateAIConfig: (payload: Partial<AIConfigData['preferences']>) =>
    apiRequest<AIConfigData>('/dashboard/ai-config', { method: 'PUT', body: JSON.stringify(payload) }),

  listOpportunities: (params: URLSearchParams) => apiRequest<OpportunitiesResponse>(`/opportunities?${params.toString()}`),
  triggerDiscovery: (source_id?: string | null, run_matching = true) =>
    apiRequest<{ runs: number; fetched: number; created: number; updated: number; matched: number }>('/opportunities/discover', {
      method: 'POST',
      body: JSON.stringify({ source_id: source_id || null, run_matching }),
    }),
  getDiscoveryHistory: () => apiRequest<DiscoveryHistoryItem[]>('/opportunities/discovery-history'),
  runMatching: () => apiRequest<{ processed: number }>('/matching/run', { method: 'POST' }),
  analyzeMatch: (opportunityId: string) => apiRequest<Record<string, unknown>>(`/matching/opportunities/${opportunityId}/analyze`, { method: 'POST' }),

  generateAndPrepare: async (opportunityId: string) => {
    await apiRequest(`/generation/opportunities/${opportunityId}`, { method: 'POST', body: JSON.stringify({ formats: ['pdf'], questions: [] }) });
    return apiRequest<{ id: string; status: string }>(`/applications/opportunities/${opportunityId}/prepare`, {
      method: 'POST',
      body: JSON.stringify({ answers: {} }),
    });
  },
  listApplications: (status?: string) => apiRequest<ApplicationsListResponse>(status ? `/applications?status=${encodeURIComponent(status)}` : '/applications'),
  getApprovalQueue: () => apiRequest<ApplicationReviewItem[]>('/applications/queue'),
  editApplication: (id: string, payload: { answers?: Record<string, string>; cv_text?: string; cover_letter_text?: string }) =>
    apiRequest<ApplicationReviewItem>(`/applications/${id}`, { method: 'PUT', body: JSON.stringify(payload) }),
  approveApplication: (id: string) => apiRequest<{ status: string }>(`/applications/${id}/approve`, { method: 'POST' }),
  rejectApplication: (id: string, reason: string) => apiRequest<{ status: string }>(`/applications/${id}/reject`, { method: 'POST', body: JSON.stringify({ reason }) }),
  submitApplication: (id: string) => apiRequest<{ id: string; status: string; confirmation_reference: string | null; last_error: string | null }>(`/applications/${id}/submit`, { method: 'POST' }),
  withdrawApplication: (id: string) => apiRequest<{ status: string }>(`/applications/${id}/withdraw`, { method: 'POST' }),

  listInterviews: () => apiRequest<InterviewItem[]>('/interviews'),
  createInterview: (payload: { application_id: string; scheduled_at: string; interview_type: string; notes: string }) =>
    apiRequest<InterviewItem>('/interviews', { method: 'POST', body: JSON.stringify(payload) }),
  deleteInterview: (id: string) => apiRequest<void>(`/interviews/${id}`, { method: 'DELETE' }),

  listDocuments: () => apiRequest<DocumentItem[]>('/documents'),
  uploadDocument: (form: FormData) => apiRequest<DocumentItem>('/documents', { method: 'POST', body: form }),
  previewDocument: (id: string) => apiRequest<string>(`/documents/${id}/preview`),
  setDefaultCv: (id: string) => apiRequest<{ status: string }>(`/documents/${id}/default`, { method: 'POST' }),
  deleteDocument: (id: string) => apiRequest<{ status: string }>(`/documents/${id}`, { method: 'DELETE' }),

  getProfile: () => apiRequest<ProfileData>('/profile'),
  updateProfile: (payload: Record<string, unknown>) => apiRequest<ProfileData>('/profile', { method: 'PUT', body: JSON.stringify(payload) }),
  addEducation: (payload: Record<string, unknown>) => apiRequest<{ id: string }>('/profile/education', { method: 'POST', body: JSON.stringify(payload) }),
  deleteEducation: (id: string) => apiRequest<{ status: string }>(`/profile/education/${id}`, { method: 'DELETE' }),
  addExperience: (payload: Record<string, unknown>) => apiRequest<{ id: string }>('/profile/experience', { method: 'POST', body: JSON.stringify(payload) }),
  deleteExperience: (id: string) => apiRequest<{ status: string }>(`/profile/experience/${id}`, { method: 'DELETE' }),
  addSkill: (payload: Record<string, unknown>) => apiRequest<{ id: string }>('/profile/skills', { method: 'POST', body: JSON.stringify(payload) }),
  deleteSkill: (id: string) => apiRequest<{ status: string }>(`/profile/skills/${id}`, { method: 'DELETE' }),
  getProfileFacts: () => apiRequest<ProfileFactItem[]>('/profile/facts'),
  confirmProfileFact: (id: string) => apiRequest<{ status: string }>(`/profile/facts/${id}/confirm`, { method: 'POST' }),

  listSources: () => apiRequest<JobSourceItem[]>('/sources'),
  createSource: (payload: { name: string; base_url: string; connector_type: string; config: Record<string, unknown> }) =>
    apiRequest<{ id: string }>('/sources', { method: 'POST', body: JSON.stringify(payload) }),
  toggleSource: (id: string) => apiRequest<{ is_active: boolean }>(`/sources/${id}/toggle`, { method: 'POST' }),
  runSource: (id: string) => apiRequest<{ status: string; fetched_count: number; created_count: number }>(`/sources/${id}/run`, { method: 'POST' }),

  listSavedSearches: () => apiRequest<SavedSearchItem[]>('/saved-searches'),
  createSavedSearch: (payload: { name: string; query: string; filters: Record<string, unknown>; is_active: boolean }) =>
    apiRequest<SavedSearchItem>('/saved-searches', { method: 'POST', body: JSON.stringify(payload) }),
  updateSavedSearch: (id: string, payload: Partial<SavedSearchItem>) =>
    apiRequest<SavedSearchItem>(`/saved-searches/${id}`, { method: 'PUT', body: JSON.stringify(payload) }),
  deleteSavedSearch: (id: string) => apiRequest<void>(`/saved-searches/${id}`, { method: 'DELETE' }),

  getNotificationSettings: () => apiRequest<NotificationSettingsData>('/notifications/settings'),
  updateNotificationSettings: (payload: Partial<NotificationSettingsData>) =>
    apiRequest<NotificationSettingsData>('/notifications/settings', { method: 'PUT', body: JSON.stringify(payload) }),
  listNotificationDeliveries: () => apiRequest<NotificationDeliveryItem[]>('/notifications/deliveries'),
  retryNotifications: () => apiRequest<{ retried: number; sent: number }>('/notifications/retry', { method: 'POST' }),
  listInAppNotifications: () => apiRequest<{ id: string; title: string; body: string; read_at: string | null; created_at: string }[]>('/notifications'),
  markNotificationRead: (id: string) => apiRequest<{ status: string }>(`/notifications/${id}/read`, { method: 'POST' }),

  getBotStatus: () => apiRequest<BotStatusData>('/bot/status'),
  pauseBot: () => apiRequest<BotStatusData['config']>('/bot/pause', { method: 'POST' }),
  resumeBot: () => apiRequest<BotStatusData['config']>('/bot/resume', { method: 'POST' }),
  pauseAutoApply: () => apiRequest<BotStatusData['config']>('/bot/auto-apply/pause', { method: 'POST' }),
  resumeAutoApply: () => apiRequest<BotStatusData['config']>('/bot/auto-apply/resume', { method: 'POST' }),
  updateBotConfig: (payload: { search_frequency_minutes?: number; match_strong_threshold?: number; match_approval_threshold?: number }) =>
    apiRequest<BotStatusData['config']>('/bot/config', { method: 'PUT', body: JSON.stringify(payload) }),
  startManualSearch: () => apiRequest<{ status?: string; runs?: number; created?: number; matched?: number }>('/bot/search-now', { method: 'POST' }),
};
