import { useState, useEffect, type FormEvent } from 'react';
import { LogIn, UserPlus, Loader2, AlertCircle, Sparkles } from 'lucide-react';
import { useAuthStore } from '../../stores/authStore';

interface LoginPageProps {
  onLoginSuccess: () => void;
}

export function LoginPage({ onLoginSuccess }: LoginPageProps) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [isBootstrap, setIsBootstrap] = useState(false);
  const [checkingBootstrap, setCheckingBootstrap] = useState(true);
  
  const { login, bootstrap, isLoading, error, clearError } = useAuthStore();

  // Check if bootstrap is needed (no users exist)
  useEffect(() => {
    const checkBootstrapNeeded = async () => {
      try {
        // Try to access a protected endpoint - if it returns 401 without
        // any users, we need bootstrap. We'll use a simple heuristic:
        // try bootstrap endpoint to see if it's available
        const response = await fetch('/api/v1/auth/bootstrap', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ email: 'test@test.com', password: 'testtest' }),
        });
        
        // If we get a 400 "users already exist", no bootstrap needed
        if (response.status === 400) {
          setIsBootstrap(false);
        } else {
          // Otherwise, bootstrap might be available
          setIsBootstrap(true);
        }
      } catch {
        setIsBootstrap(false);
      } finally {
        setCheckingBootstrap(false);
      }
    };

    checkBootstrapNeeded();
  }, []);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    clearError();
    
    let success: boolean;
    if (isBootstrap) {
      success = await bootstrap(email, password);
    } else {
      success = await login(email, password);
    }
    
    if (success) {
      onLoginSuccess();
    }
  };

  if (checkingBootstrap) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-slate-100 to-slate-200 dark:from-slate-900 dark:to-slate-800">
        <Loader2 className="w-8 h-8 text-blue-500 animate-spin" />
      </div>
    );
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-slate-100 to-slate-200 dark:from-slate-900 dark:to-slate-800 p-4">
      <div className="w-full max-w-md">
        {/* Logo/Header */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-16 h-16 rounded-full bg-blue-600/20 mb-4">
            <Sparkles className="w-8 h-8 text-blue-500 dark:text-blue-400" />
          </div>
          <h1 className="text-2xl font-bold text-slate-900 dark:text-white">Agent System</h1>
          <p className="text-slate-600 dark:text-slate-400 mt-2">
            {isBootstrap 
              ? 'Create your admin account to get started'
              : 'Sign in to continue'
            }
          </p>
        </div>

        {/* Login Form */}
        <div className="bg-white/80 dark:bg-slate-800/50 backdrop-blur-sm rounded-xl border border-slate-300 dark:border-slate-700 p-6 shadow-xl">
          {isBootstrap && (
            <div className="mb-6 p-4 bg-blue-100 dark:bg-blue-900/30 border border-blue-300 dark:border-blue-700/50 rounded-lg">
              <div className="flex items-start gap-3">
                <UserPlus className="w-5 h-5 text-blue-600 dark:text-blue-400 mt-0.5" />
                <div>
                  <h3 className="font-medium text-blue-700 dark:text-blue-300">First-time Setup</h3>
                  <p className="text-sm text-blue-600/70 dark:text-blue-300/70 mt-1">
                    Create the first admin account. This account will have full access
                    to manage users and settings.
                  </p>
                </div>
              </div>
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label htmlFor="email" className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">
                Email
              </label>
              <input
                id="email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="w-full px-4 py-3 bg-slate-50 dark:bg-slate-900/50 border border-slate-300 dark:border-slate-600 rounded-lg text-base text-slate-900 dark:text-white placeholder-slate-400 dark:placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-all"
                placeholder="admin@example.com"
                required
                autoFocus
                autoComplete="email"
              />
            </div>

            <div>
              <label htmlFor="password" className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">
                Password
              </label>
              <input
                id="password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full px-4 py-3 bg-slate-50 dark:bg-slate-900/50 border border-slate-300 dark:border-slate-600 rounded-lg text-base text-slate-900 dark:text-white placeholder-slate-400 dark:placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-all"
                placeholder={isBootstrap ? 'At least 8 characters' : '••••••••'}
                minLength={isBootstrap ? 8 : 1}
                required
                autoComplete={isBootstrap ? 'new-password' : 'current-password'}
              />
            </div>

            {error && (
              <div className="flex items-center gap-2 p-3 bg-red-100 dark:bg-red-900/30 border border-red-300 dark:border-red-700/50 rounded-lg text-red-700 dark:text-red-300 text-sm">
                <AlertCircle className="w-4 h-4 shrink-0" />
                <span>{error}</span>
              </div>
            )}

            <button
              type="submit"
              disabled={isLoading}
              className="w-full flex items-center justify-center gap-2 px-4 py-3 bg-blue-600 hover:bg-blue-700 disabled:bg-blue-600/50 text-white font-medium rounded-lg transition-colors"
            >
              {isLoading ? (
                <Loader2 className="w-5 h-5 animate-spin" />
              ) : isBootstrap ? (
                <>
                  <UserPlus className="w-5 h-5" />
                  Create Admin Account
                </>
              ) : (
                <>
                  <LogIn className="w-5 h-5" />
                  Sign In
                </>
              )}
            </button>
          </form>

          {!isBootstrap && (
            <p className="text-center text-sm text-slate-500 mt-6">
              Don't have an account?{' '}
              <span className="text-slate-600 dark:text-slate-400">Contact your administrator</span>
            </p>
          )}
        </div>

        {/* Footer */}
        <p className="text-center text-xs text-slate-500 mt-6">
          Powered by PydanticAI • Hexagonal Architecture
        </p>
      </div>
    </div>
  );
}
