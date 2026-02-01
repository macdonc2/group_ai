import { useState, useEffect } from 'react';
import { X, UserPlus, Trash2, Ban, Loader2, ShieldCheck, Copy, Check } from 'lucide-react';
import { api } from '../../lib/api';

interface User {
  id: string;
  email: string;
  is_active: boolean;
  is_verified: boolean;
  is_superuser: boolean;
  created_at: string;
}

interface UserManagementProps {
  onClose: () => void;
  currentUserId: string;
}

// Generate a random temporary password
function generateTempPassword(): string {
  const chars = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz23456789';
  let password = '';
  for (let i = 0; i < 12; i++) {
    password += chars.charAt(Math.floor(Math.random() * chars.length));
  }
  return password;
}

export function UserManagement({ onClose, currentUserId }: UserManagementProps) {
  const [users, setUsers] = useState<User[]>([]);
  const [loading, setLoading] = useState(true);
  const [newEmail, setNewEmail] = useState('');
  const [creating, setCreating] = useState(false);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [createdUser, setCreatedUser] = useState<{ email: string; password: string } | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    loadUsers();
  }, []);

  const loadUsers = async () => {
    try {
      const data = await api.listUsers();
      setUsers(data);
    } catch (err) {
      setError('Failed to load users');
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  const handleCreateUser = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newEmail) return;

    const tempPassword = generateTempPassword();
    setCreating(true);
    setError(null);
    
    try {
      const user = await api.createUser(newEmail, tempPassword);
      setUsers([...users, user]);
      setCreatedUser({ email: newEmail, password: tempPassword });
      setNewEmail('');
    } catch (err: any) {
      const message = err.message || 'Failed to create user';
      setError(message.includes('already') ? 'Email already registered' : message);
      console.error(err);
    } finally {
      setCreating(false);
    }
  };

  const copyCredentials = () => {
    if (createdUser) {
      navigator.clipboard.writeText(`Email: ${createdUser.email}\nPassword: ${createdUser.password}`);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  const handleVerify = async (userId: string) => {
    setActionLoading(userId);
    try {
      await api.verifyUser(userId);
      setUsers(users.map((u) => (u.id === userId ? { ...u, is_verified: true } : u)));
    } catch (err) {
      setError('Failed to verify user');
    } finally {
      setActionLoading(null);
    }
  };

  const handleDeactivate = async (userId: string) => {
    if (!window.confirm('Deactivate this user? They will not be able to log in.')) return;
    setActionLoading(userId);
    try {
      await api.deactivateUser(userId);
      setUsers(users.map((u) => (u.id === userId ? { ...u, is_active: false } : u)));
    } catch (err) {
      setError('Failed to deactivate user');
    } finally {
      setActionLoading(null);
    }
  };

  const handleDelete = async (userId: string, email: string) => {
    if (!window.confirm(`Delete user ${email}? This cannot be undone.`)) return;
    setActionLoading(userId);
    try {
      await api.deleteUser(userId);
      setUsers(users.filter((u) => u.id !== userId));
    } catch (err) {
      setError('Failed to delete user');
    } finally {
      setActionLoading(null);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-start justify-center z-50 pt-16 overflow-y-auto">
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-xl w-full max-w-lg mx-4 mb-8">
        {/* Header */}
        <div className="flex items-center justify-between p-3 border-b dark:border-gray-700">
          <h2 className="font-semibold text-gray-900 dark:text-gray-100">User Management</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300">
            <X size={20} />
          </button>
        </div>

        <div className="p-4">
          {/* Error */}
          {error && (
            <div className="mb-3 p-2 bg-red-50 dark:bg-red-900/20 text-red-600 dark:text-red-400 rounded text-sm flex justify-between">
              {error}
              <button onClick={() => setError(null)}><X size={14} /></button>
            </div>
          )}

          {/* Created User Credentials */}
          {createdUser && (
            <div className="mb-4 p-3 bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 rounded-lg">
              <p className="text-sm font-medium text-green-800 dark:text-green-200 mb-2">
                User created! Share these credentials:
              </p>
              <div className="bg-white dark:bg-gray-800 p-2 rounded text-sm font-mono">
                <div>Email: {createdUser.email}</div>
                <div>Password: {createdUser.password}</div>
              </div>
              <div className="flex gap-2 mt-2">
                <button
                  onClick={copyCredentials}
                  className="flex items-center px-3 py-1 text-sm bg-green-600 hover:bg-green-700 text-white rounded transition-colors"
                >
                  {copied ? <Check size={14} className="mr-1" /> : <Copy size={14} className="mr-1" />}
                  {copied ? 'Copied!' : 'Copy'}
                </button>
                <button
                  onClick={() => setCreatedUser(null)}
                  className="px-3 py-1 text-sm text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 rounded transition-colors"
                >
                  Dismiss
                </button>
              </div>
              <p className="text-xs text-green-700 dark:text-green-300 mt-2">
                User should change password after first login.
              </p>
            </div>
          )}

          {/* Create User - Inline form */}
          <form onSubmit={handleCreateUser} className="flex gap-2 mb-4">
            <input
              type="email"
              value={newEmail}
              onChange={(e) => setNewEmail(e.target.value)}
              placeholder="New user email"
              required
              className="flex-1 px-3 py-2 text-sm border dark:border-gray-600 rounded bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
            <button
              type="submit"
              disabled={creating || !newEmail}
              className="flex items-center px-3 py-2 bg-blue-600 hover:bg-blue-700 disabled:bg-blue-400 text-white text-sm rounded transition-colors"
            >
              {creating ? <Loader2 className="animate-spin" size={16} /> : <UserPlus size={16} />}
            </button>
          </form>

          {/* User List */}
          {loading ? (
            <div className="flex justify-center py-6">
              <Loader2 className="animate-spin text-gray-400" size={24} />
            </div>
          ) : users.length === 0 ? (
            <p className="text-center py-6 text-gray-500 dark:text-gray-400 text-sm">No users yet.</p>
          ) : (
            <div className="space-y-1 max-h-64 overflow-y-auto">
              {users.map((user) => (
                <div
                  key={user.id}
                  className={`flex items-center justify-between p-2 rounded hover:bg-gray-50 dark:hover:bg-gray-700/50 ${
                    !user.is_active ? 'opacity-50' : ''
                  }`}
                >
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-1">
                      <span className="text-sm truncate">{user.email}</span>
                      {user.is_superuser && (
                        <span className="px-1.5 py-0.5 text-xs bg-purple-100 dark:bg-purple-900/30 text-purple-600 dark:text-purple-400 rounded">
                          Admin
                        </span>
                      )}
                      {user.id === currentUserId && <span className="text-xs text-gray-400">(you)</span>}
                    </div>
                    <div className="flex gap-2 text-xs text-gray-500">
                      <span className={user.is_active ? 'text-green-600' : 'text-red-500'}>
                        {user.is_active ? 'Active' : 'Inactive'}
                      </span>
                      <span className={user.is_verified ? 'text-blue-600' : 'text-yellow-600'}>
                        {user.is_verified ? 'Verified' : 'Pending'}
                      </span>
                    </div>
                  </div>

                  {user.id !== currentUserId && (
                    <div className="flex items-center">
                      {!user.is_verified && user.is_active && (
                        <button
                          onClick={() => handleVerify(user.id)}
                          disabled={actionLoading === user.id}
                          className="p-1.5 text-blue-600 hover:bg-blue-50 dark:hover:bg-blue-900/20 rounded"
                          title="Verify"
                        >
                          <ShieldCheck size={14} />
                        </button>
                      )}
                      {user.is_active && (
                        <button
                          onClick={() => handleDeactivate(user.id)}
                          disabled={actionLoading === user.id}
                          className="p-1.5 text-yellow-600 hover:bg-yellow-50 dark:hover:bg-yellow-900/20 rounded"
                          title="Deactivate"
                        >
                          <Ban size={14} />
                        </button>
                      )}
                      <button
                        onClick={() => handleDelete(user.id, user.email)}
                        disabled={actionLoading === user.id}
                        className="p-1.5 text-red-600 hover:bg-red-50 dark:hover:bg-red-900/20 rounded"
                        title="Delete"
                      >
                        <Trash2 size={14} />
                      </button>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
