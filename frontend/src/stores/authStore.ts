import { create } from 'zustand';
import { persist } from 'zustand/middleware';

export interface User {
  id: string;
  email: string;
  is_active: boolean;
  is_verified: boolean;
  is_superuser: boolean;
  created_at: string;
}

interface AuthState {
  token: string | null;
  user: User | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  error: string | null;
  
  // Actions
  login: (email: string, password: string) => Promise<boolean>;
  logout: () => void;
  bootstrap: (email: string, password: string) => Promise<boolean>;
  checkAuth: () => Promise<boolean>;
  clearError: () => void;
}

const API_BASE = '/api/v1';

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      token: null,
      user: null,
      isAuthenticated: false,
      isLoading: false,
      error: null,

      login: async (email: string, password: string) => {
        set({ isLoading: true, error: null });
        
        try {
          const response = await fetch(`${API_BASE}/auth/login`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email, password }),
          });
          
          if (!response.ok) {
            const data = await response.json();
            set({ 
              isLoading: false, 
              error: data.detail || 'Login failed',
            });
            return false;
          }
          
          const data = await response.json();
          
          set({
            token: data.access_token,
            user: data.user,
            isAuthenticated: true,
            isLoading: false,
            error: null,
          });
          
          return true;
        } catch (error) {
          set({ 
            isLoading: false, 
            error: 'Network error. Please try again.',
          });
          return false;
        }
      },

      logout: () => {
        set({
          token: null,
          user: null,
          isAuthenticated: false,
          error: null,
        });
      },

      bootstrap: async (email: string, password: string) => {
        set({ isLoading: true, error: null });
        
        try {
          const response = await fetch(`${API_BASE}/auth/bootstrap`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email, password, is_superuser: true }),
          });
          
          if (!response.ok) {
            const data = await response.json();
            set({ 
              isLoading: false, 
              error: data.detail || 'Bootstrap failed',
            });
            return false;
          }
          
          const data = await response.json();
          
          set({
            token: data.access_token,
            user: data.user,
            isAuthenticated: true,
            isLoading: false,
            error: null,
          });
          
          return true;
        } catch (error) {
          set({ 
            isLoading: false, 
            error: 'Network error. Please try again.',
          });
          return false;
        }
      },

      checkAuth: async () => {
        const { token } = get();
        
        if (!token) {
          return false;
        }
        
        try {
          const response = await fetch(`${API_BASE}/auth/me`, {
            headers: {
              'Authorization': `Bearer ${token}`,
            },
          });
          
          if (!response.ok) {
            // Token is invalid, clear auth state
            set({
              token: null,
              user: null,
              isAuthenticated: false,
            });
            return false;
          }
          
          const user = await response.json();
          set({ user, isAuthenticated: true });
          return true;
        } catch (error) {
          return false;
        }
      },

      clearError: () => {
        set({ error: null });
      },
    }),
    {
      name: 'auth-storage',
      partialize: (state) => ({ 
        token: state.token,
        user: state.user,
        isAuthenticated: state.isAuthenticated,
      }),
    }
  )
);

// Helper function to get auth header
export function getAuthHeader(): Record<string, string> {
  const token = useAuthStore.getState().token;
  if (token) {
    return { 'Authorization': `Bearer ${token}` };
  }
  return {};
}
