import { useState, useEffect } from 'react';
import { X, UserPlus, Search, Loader2 } from 'lucide-react';
import { api } from '../../lib/api';

interface User {
  id: string;
  email: string;
  is_active: boolean;
  is_verified: boolean;
}

interface AddMemberModalProps {
  groupId: string;
  existingMemberIds: string[];
  onClose: () => void;
  onMemberAdded: () => void;
}

export function AddMemberModal({
  groupId,
  existingMemberIds,
  onClose,
  onMemberAdded,
}: AddMemberModalProps) {
  const [users, setUsers] = useState<User[]>([]);
  const [loading, setLoading] = useState(true);
  const [adding, setAdding] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;
    
    const loadUsers = async () => {
      try {
        const allUsers = await api.searchUsers();
        if (!mounted) return;
        
        // Filter out existing members and inactive users
        const availableUsers = (allUsers || []).filter(
          (u) => !existingMemberIds.includes(u.id) && u.is_active
        );
        setUsers(availableUsers);
      } catch (err) {
        if (!mounted) return;
        const message = err instanceof Error ? err.message : 'Failed to load users';
        setError(message);
        console.error('AddMemberModal loadUsers error:', err);
      } finally {
        if (mounted) {
          setLoading(false);
        }
      }
    };
    
    loadUsers();
    
    return () => {
      mounted = false;
    };
  }, [existingMemberIds]);

  const handleAddMember = async (userId: string) => {
    setAdding(userId);
    setError(null);
    try {
      await api.addGroupMember(groupId, userId);
      setUsers(users.filter((u) => u.id !== userId));
      onMemberAdded();
    } catch (err) {
      setError('Failed to add member');
      console.error(err);
    } finally {
      setAdding(null);
    }
  };

  const filteredUsers = users.filter((u) =>
    u.email.toLowerCase().includes(search.toLowerCase())
  );

  return (
    <div 
      className="fixed inset-0 bg-black/50 flex items-center justify-center z-50"
      onClick={(e) => {
        // Only close if clicking the backdrop itself
        if (e.target === e.currentTarget) {
          onClose();
        }
      }}
    >
      <div 
        className="bg-white dark:bg-gray-800 rounded-lg shadow-xl w-full max-w-md mx-4"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between p-4 border-b dark:border-gray-700">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">
            Add Member
          </h2>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300"
          >
            <X size={20} />
          </button>
        </div>

        <div className="p-4">
          {/* Search */}
          <div className="relative mb-4">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" size={18} />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search users by email..."
              className="w-full pl-10 pr-4 py-2 border dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>

          {error && (
            <div className="mb-4 p-3 bg-red-50 dark:bg-red-900/20 text-red-600 dark:text-red-400 rounded-lg text-sm">
              {error}
            </div>
          )}

          {/* User List */}
          <div className="max-h-64 overflow-y-auto">
            {loading ? (
              <div className="flex items-center justify-center py-8">
                <Loader2 className="animate-spin text-gray-400" size={24} />
              </div>
            ) : filteredUsers.length === 0 ? (
              <div className="text-center py-8 text-gray-500 dark:text-gray-400">
                {users.length === 0
                  ? 'No users available to add. Create new users first.'
                  : 'No users match your search.'}
              </div>
            ) : (
              <div className="space-y-2">
                {filteredUsers.map((user) => (
                  <div
                    key={user.id}
                    className="flex items-center justify-between p-3 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700/50 transition-colors"
                  >
                    <div>
                      <p className="text-sm font-medium text-gray-900 dark:text-gray-100">
                        {user.email}
                      </p>
                      <p className="text-xs text-gray-500 dark:text-gray-400">
                        {user.is_verified ? 'Verified' : 'Pending verification'}
                      </p>
                    </div>
                    <button
                      onClick={() => handleAddMember(user.id)}
                      disabled={adding === user.id}
                      className="flex items-center px-3 py-1.5 bg-blue-600 hover:bg-blue-700 disabled:bg-blue-400 text-white text-sm rounded-lg transition-colors"
                    >
                      {adding === user.id ? (
                        <Loader2 className="animate-spin" size={16} />
                      ) : (
                        <>
                          <UserPlus size={16} className="mr-1" />
                          Add
                        </>
                      )}
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        <div className="p-4 border-t dark:border-gray-700 bg-gray-50 dark:bg-gray-800/50 rounded-b-lg">
          <p className="text-xs text-gray-500 dark:text-gray-400 text-center">
            Need to create a new user? Go to Settings → User Management
          </p>
        </div>
      </div>
    </div>
  );
}
