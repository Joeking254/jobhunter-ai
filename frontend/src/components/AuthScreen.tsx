import { useState, type FormEvent } from 'react';
import { Sparkles, Moon, Sun } from 'lucide-react';
import { api, type User } from '../api/client';

export function AuthScreen({
  onAuthenticated,
  theme,
  onToggleTheme,
}: {
  onAuthenticated: (user: User) => void;
  theme: 'dark' | 'light';
  onToggleTheme: () => void;
}) {
  const [mode, setMode] = useState<'login' | 'register'>('login');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [firstName, setFirstName] = useState('');
  const [lastName, setLastName] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const user =
        mode === 'login'
          ? await api.login(email, password)
          : await api.register({ email, password, first_name: firstName, last_name: lastName });
      onAuthenticated(user);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Authentication failed');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="auth-shell">
      <div className="auth-topbar">
        <div className="brand">
          <Sparkles size={20} className="brand-icon" />
          <span>JOBHUNTER AI</span>
        </div>
        <button type="button" className="btn btn-ghost btn-sm" onClick={onToggleTheme} aria-label="Toggle theme">
          {theme === 'dark' ? <Sun size={16} /> : <Moon size={16} />}
          <span>{theme === 'dark' ? 'Light mode' : 'Dark mode'}</span>
        </button>
      </div>
      <div className="card auth-card">
        <h1>{mode === 'login' ? 'Sign in to your workspace' : 'Create your owner account'}</h1>
        <p className="muted">
          {mode === 'login'
            ? 'Manage opportunity discovery, AI matching, approval queues, and application telemetry.'
            : 'Use a password of at least 12 characters with upper, lower, and numeric characters.'}
        </p>
        {error && <div className="alert alert-error">{error}</div>}
        <form onSubmit={handleSubmit} className="stack">
          {mode === 'register' && (
            <div className="grid-2">
              <label className="field">
                <span>First name</span>
                <input required value={firstName} onChange={(e) => setFirstName(e.target.value)} placeholder="Ada" />
              </label>
              <label className="field">
                <span>Last name</span>
                <input required value={lastName} onChange={(e) => setLastName(e.target.value)} placeholder="Lovelace" />
              </label>
            </div>
          )}
          <label className="field">
            <span>Email</span>
            <input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@example.com" />
          </label>
          <label className="field">
            <span>Password</span>
            <input type="password" required value={password} onChange={(e) => setPassword(e.target.value)} placeholder="••••••••••••" />
          </label>
          <button type="submit" className="btn btn-primary" disabled={loading}>
            {loading ? 'Please wait...' : mode === 'login' ? 'Sign in' : 'Create account'}
          </button>
        </form>
        <div className="auth-switch">
          {mode === 'login' ? (
            <button type="button" className="btn-link" onClick={() => setMode('register')}>
              Need an account? Register
            </button>
          ) : (
            <button type="button" className="btn-link" onClick={() => setMode('login')}>
              Already have an account? Sign in
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
