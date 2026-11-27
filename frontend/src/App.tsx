import { useCallback, useEffect, useState } from 'react';
import {
  BarChart3,
  Bell,
  Briefcase,
  CalendarCheck,
  CheckSquare,
  Compass,
  FileText,
  Globe,
  History,
  LayoutDashboard,
  Menu,
  Moon,
  Search,
  Settings,
  Sliders,
  Sparkles,
  Sun,
  User as UserIcon,
  X,
} from 'lucide-react';
import { api, type JobSourceItem, type User } from './api/client';
import { ApprovalQueueView } from './components/ApprovalQueueView';
import { AuthScreen } from './components/AuthScreen';
import { OpportunitiesView } from './components/OpportunitiesView';
import {
  ApplicationHistoryPage,
  DiscoveryPage,
  DocumentsPage,
  InterviewTrackerPage,
  ProfilePage,
} from './components/OperationsPages';
import { AnalyticsPage, OverviewPage } from './components/OverviewAndAnalytics';
import {
  AIConfigPage,
  AccountSettingsPage,
  NotificationSettingsPage,
  SearchConfigPage,
  SourcesPage,
} from './components/SettingsPages';

export type PageId =
  | 'overview'
  | 'discovery'
  | 'all-opportunities'
  | 'recommended'
  | 'approvals'
  | 'applications'
  | 'interviews'
  | 'documents'
  | 'profile'
  | 'sources'
  | 'search-config'
  | 'ai-config'
  | 'notifications'
  | 'analytics'
  | 'account';

interface NavItem {
  id: PageId;
  label: string;
  group: 'Workspace' | 'Pipeline' | 'Profile & Assets' | 'Configuration';
  icon: typeof LayoutDashboard;
}

export const NAV_ITEMS: NavItem[] = [
  { id: 'overview', label: 'Overview', group: 'Workspace', icon: LayoutDashboard },
  { id: 'analytics', label: 'Analytics', group: 'Workspace', icon: BarChart3 },
  { id: 'discovery', label: 'Opportunity Discovery', group: 'Pipeline', icon: Compass },
  { id: 'all-opportunities', label: 'All Opportunities', group: 'Pipeline', icon: Briefcase },
  { id: 'recommended', label: 'Recommended Opportunities', group: 'Pipeline', icon: Sparkles },
  { id: 'approvals', label: 'Pending Approvals', group: 'Pipeline', icon: CheckSquare },
  { id: 'applications', label: 'Application History', group: 'Pipeline', icon: History },
  { id: 'interviews', label: 'Interview Tracker', group: 'Pipeline', icon: CalendarCheck },
  { id: 'documents', label: 'CV & Documents', group: 'Profile & Assets', icon: FileText },
  { id: 'profile', label: 'Career Profile', group: 'Profile & Assets', icon: UserIcon },
  { id: 'sources', label: 'Job Source Management', group: 'Configuration', icon: Globe },
  { id: 'search-config', label: 'Search Configuration', group: 'Configuration', icon: Search },
  { id: 'ai-config', label: 'AI Configuration', group: 'Configuration', icon: Sliders },
  { id: 'notifications', label: 'Notification Settings', group: 'Configuration', icon: Bell },
  { id: 'account', label: 'Account Settings', group: 'Configuration', icon: Settings },
];

const GROUPS: NavItem['group'][] = ['Workspace', 'Pipeline', 'Profile & Assets', 'Configuration'];

function App() {
  const [user, setUser] = useState<User | null>(null);
  const [authChecked, setAuthChecked] = useState(false);
  const [page, setPage] = useState<PageId>('overview');
  const [theme, setTheme] = useState<'dark' | 'light'>(() => {
    const saved = typeof window !== 'undefined' ? window.localStorage.getItem('jobhunter_theme') : null;
    return saved === 'light' ? 'light' : 'dark';
  });
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [sources, setSources] = useState<JobSourceItem[]>([]);
  const [searchSeed, setSearchSeed] = useState('');
  const [toast, setToast] = useState<{ text: string; error?: boolean } | null>(null);
  const [refreshTick, setRefreshTick] = useState(0);

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
    try {
      window.localStorage.setItem('jobhunter_theme', theme);
    } catch {
      // ignore storage errors
    }
  }, [theme]);

  const notify = useCallback((text: string, error = false) => {
    setToast({ text, error });
  }, []);

  useEffect(() => {
    if (!toast) return;
    const t = window.setTimeout(() => setToast(null), 4000);
    return () => window.clearTimeout(t);
  }, [toast]);

  const loadSession = useCallback(async () => {
    try {
      const current = await api.me();
      setUser(current);
    } catch {
      setUser(null);
    } finally {
      setAuthChecked(true);
    }
  }, []);

  const loadSources = useCallback(async () => {
    try {
      setSources(await api.listSources());
    } catch {
      // ignore if empty
    }
  }, []);

  useEffect(() => {
    void loadSession();
  }, [loadSession]);

  useEffect(() => {
    if (user) void loadSources();
  }, [user, loadSources]);

  function navigateTo(target: string) {
    if (NAV_ITEMS.some((n) => n.id === target)) {
      setPage(target as PageId);
      setMobileMenuOpen(false);
    }
  }

  function toggleTheme() {
    setTheme((prev) => (prev === 'dark' ? 'light' : 'dark'));
  }

  if (!authChecked) {
    return (
      <div className="loading-screen">
        <Sparkles size={24} className="brand-icon" />
        <span>Loading JOBHUNTER AI...</span>
      </div>
    );
  }

  if (!user) {
    return <AuthScreen onAuthenticated={setUser} theme={theme} onToggleTheme={toggleTheme} />;
  }

  const activeNav = NAV_ITEMS.find((item) => item.id === page) ?? NAV_ITEMS[0];

  return (
    <div className="dashboard-shell">
      {mobileMenuOpen && (
        <div
          className="sidebar-backdrop"
          onClick={() => setMobileMenuOpen(false)}
          aria-hidden="true"
        />
      )}

      <aside className={`sidebar ${mobileMenuOpen ? 'open' : ''}`} aria-label="Sidebar navigation">
        <div className="sidebar-brand">
          <div className="brand">
            <Sparkles size={19} className="brand-icon" />
            <span>JOBHUNTER AI</span>
          </div>
          <button
            type="button"
            className="btn btn-ghost btn-sm mobile-only"
            onClick={() => setMobileMenuOpen(false)}
            aria-label="Close navigation menu"
          >
            <X size={18} />
          </button>
        </div>

        <nav className="sidebar-nav">
          {GROUPS.map((group) => (
            <div key={group} className="nav-group">
              <div className="nav-group-label">{group}</div>
              {NAV_ITEMS.filter((item) => item.group === group).map((item) => {
                const Icon = item.icon;
                return (
                  <button
                    key={item.id}
                    type="button"
                    className={`nav-link ${page === item.id ? 'active' : ''}`}
                    onClick={() => navigateTo(item.id)}
                    aria-current={page === item.id ? 'page' : undefined}
                  >
                    <Icon size={16} />
                    <span>{item.label}</span>
                  </button>
                );
              })}
            </div>
          ))}
        </nav>

        <div className="sidebar-footer">
          <div className="user-chip">
            <div className="avatar">{user.first_name[0]}{user.last_name[0]}</div>
            <div className="user-meta">
              <strong>{user.first_name} {user.last_name}</strong>
              <span className="muted small">{user.email}</span>
            </div>
          </div>
        </div>
      </aside>

      <div className="main-column">
        <header className="topbar">
          <div className="topbar-left">
            <button
              type="button"
              className="btn btn-ghost btn-sm mobile-only"
              onClick={() => setMobileMenuOpen(true)}
              aria-label="Open navigation menu"
            >
              <Menu size={18} />
            </button>
            <div>
              <h1 className="page-title">{activeNav.label}</h1>
            </div>
          </div>

          <div className="topbar-actions">
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={() => navigateTo('approvals')}
            >
              <CheckSquare size={15} /> Approval Queue
            </button>
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={toggleTheme}
              aria-label="Toggle color theme"
            >
              {theme === 'dark' ? <Sun size={16} /> : <Moon size={16} />}
              <span className="hide-sm">{theme === 'dark' ? 'Light' : 'Dark'}</span>
            </button>
          </div>
        </header>

        {toast && (
          <div className={`toast ${toast.error ? 'toast-error' : 'toast-ok'}`} role="status">
            {toast.text}
          </div>
        )}

        <main className="content-area">
          {page === 'overview' && <OverviewPage key={`ov-${refreshTick}`} onNavigate={navigateTo} onNotify={notify} />}
          {page === 'discovery' && <DiscoveryPage sources={sources} onNotify={notify} />}
          {page === 'all-opportunities' && (
            <OpportunitiesView
              key={`all-${searchSeed}`}
              recommendedOnly={false}
              initialQuery={searchSeed}
              sources={sources}
              onNavigate={navigateTo}
              onNotify={notify}
            />
          )}
          {page === 'recommended' && (
            <OpportunitiesView
              key="rec"
              recommendedOnly
              sources={sources}
              onNavigate={navigateTo}
              onNotify={notify}
            />
          )}
          {page === 'approvals' && (
            <ApprovalQueueView
              onNotify={notify}
              onChanged={() => setRefreshTick((t) => t + 1)}
            />
          )}
          {page === 'applications' && <ApplicationHistoryPage onNotify={notify} />}
          {page === 'interviews' && <InterviewTrackerPage onNotify={notify} />}
          {page === 'documents' && <DocumentsPage onNotify={notify} />}
          {page === 'profile' && <ProfilePage onNotify={notify} />}
          {page === 'sources' && <SourcesPage sources={sources} onRefresh={loadSources} onNotify={notify} />}
          {page === 'search-config' && (
            <SearchConfigPage
              onApplySearch={(query) => {
                setSearchSeed(query);
                navigateTo('all-opportunities');
              }}
              onNotify={notify}
            />
          )}
          {page === 'ai-config' && <AIConfigPage onNotify={notify} />}
          {page === 'notifications' && <NotificationSettingsPage onNotify={notify} />}
          {page === 'analytics' && <AnalyticsPage onNotify={notify} />}
          {page === 'account' && (
            <AccountSettingsPage
              onUserUpdated={loadSession}
              onLoggedOut={() => setUser(null)}
              onNotify={notify}
            />
          )}
        </main>
      </div>
    </div>
  );
}

export default App;
