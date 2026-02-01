import { useState } from 'react';
import { User, Shield, ShieldOff, UserMinus, Crown, UserPlus } from 'lucide-react';
import type { GroupMember } from '../../types';
import { api } from '../../lib/api';
import { AddMemberModal } from './AddMemberModal';

interface GroupMembersProps {
  groupId: string;
  members: GroupMember[];
  currentUserId: string;
  createdBy: string;
  onlineUsers: string[];
  onRefresh: () => void;
}

export function GroupMembers({
  groupId,
  members,
  currentUserId,
  createdBy: _createdBy,
  onlineUsers,
  onRefresh,
}: GroupMembersProps) {
  // Note: createdBy passed for potential future use (ownership display)
  const [isUpdating, setIsUpdating] = useState<string | null>(null);
  const [showAddMember, setShowAddMember] = useState(false);

  // Check if current user is the owner
  const currentUserMember = members.find((m) => m.user_id === currentUserId);
  const isOwner = currentUserMember?.role === 'owner';

  const handleToggleSharing = async (member: GroupMember) => {
    if (member.user_id !== currentUserId) return;
    
    setIsUpdating(member.id);
    try {
      await api.updateMemberSettings(groupId, member.user_id, !member.sharing_enabled);
      onRefresh();
    } catch (error) {
      console.error('Failed to update sharing settings:', error);
    } finally {
      setIsUpdating(null);
    }
  };

  const handleRemoveMember = async (member: GroupMember) => {
    if (members.length === 1) {
      alert('Cannot remove the last member. Delete the group instead.');
      return;
    }

    // Owner cannot leave
    if (member.role === 'owner' && member.user_id === currentUserId) {
      alert('As the owner, you cannot leave the group. Transfer ownership or delete the group.');
      return;
    }

    const confirmed = window.confirm(
      member.user_id === currentUserId
        ? 'Are you sure you want to leave this group?'
        : `Remove ${member.user_email || 'this member'} from the group?`
    );
    if (!confirmed) return;

    setIsUpdating(member.id);
    try {
      await api.removeGroupMember(groupId, member.user_id);
      onRefresh();
    } catch (error) {
      console.error('Failed to remove member:', error);
    } finally {
      setIsUpdating(null);
    }
  };

  // Check if remove button should be shown
  const canRemoveMember = (member: GroupMember) => {
    const isCurrentUser = member.user_id === currentUserId;
    // Owner can remove anyone except themselves
    // Non-owners can only remove themselves (leave)
    if (isOwner && !isCurrentUser) return true;
    if (isCurrentUser && member.role !== 'owner') return true;
    return false;
  };

  return (
    <div className="p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">
          Members ({members.length})
        </h3>
        {isOwner && (
          <button
            onClick={() => setShowAddMember(true)}
            className="flex items-center px-2 py-1 text-xs bg-blue-600 hover:bg-blue-700 text-white rounded transition-colors"
          >
            <UserPlus size={14} className="mr-1" />
            Add
          </button>
        )}
      </div>

      {showAddMember && (
        <AddMemberModal
          groupId={groupId}
          existingMemberIds={(members || []).map((m) => m.user_id)}
          onClose={() => setShowAddMember(false)}
          onMemberAdded={() => {
            setShowAddMember(false);
            onRefresh();
          }}
        />
      )}

      <div className="space-y-2">
        {members.map((member) => {
          const isOnline = onlineUsers.includes(member.user_id);
          const isCurrentUser = member.user_id === currentUserId;
          const isMemberOwner = member.role === 'owner';

          return (
            <div
              key={member.id}
              className="flex items-center justify-between p-2 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700/50 transition-colors"
            >
              <div className="flex items-center">
                <div className="relative">
                  <div className="w-8 h-8 bg-gray-300 dark:bg-gray-600 rounded-full flex items-center justify-center">
                    <User className="text-gray-600 dark:text-gray-300" size={16} />
                  </div>
                  {isOnline && (
                    <div className="absolute -bottom-0.5 -right-0.5 w-3 h-3 bg-green-500 rounded-full border-2 border-white dark:border-gray-800" />
                  )}
                </div>
                <div className="ml-3">
                  <div className="flex items-center">
                    <p className="text-sm font-medium text-gray-900 dark:text-gray-100">
                      {member.user_email || member.user_id.slice(0, 8)}
                    </p>
                    {isCurrentUser && (
                      <span className="ml-2 text-xs text-gray-500">(you)</span>
                    )}
                    {isMemberOwner && (
                      <span className="ml-1 inline-flex items-center px-1.5 py-0.5 rounded text-xs font-medium bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-300">
                        <Crown size={10} className="mr-0.5" />
                        Owner
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-gray-500 dark:text-gray-400">
                    {isOnline ? 'Online' : (
                      member.last_seen_at 
                        ? `Last seen ${new Date(member.last_seen_at).toLocaleDateString()}`
                        : 'Offline'
                    )}
                  </p>
                </div>
              </div>

              <div className="flex items-center space-x-1">
                {isCurrentUser && (
                  <button
                    onClick={() => handleToggleSharing(member)}
                    disabled={isUpdating === member.id}
                    className={`p-1.5 rounded transition-colors ${
                      member.sharing_enabled
                        ? 'text-green-600 hover:bg-green-50 dark:hover:bg-green-900/20'
                        : 'text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700'
                    }`}
                    title={member.sharing_enabled ? 'Sharing enabled' : 'Sharing disabled (your messages won\'t be included in summaries)'}
                  >
                    {member.sharing_enabled ? <Shield size={16} /> : <ShieldOff size={16} />}
                  </button>
                )}
                {canRemoveMember(member) && (
                  <button
                    onClick={() => handleRemoveMember(member)}
                    disabled={isUpdating === member.id}
                    className="p-1.5 text-gray-400 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20 rounded transition-colors"
                    title={isCurrentUser ? 'Leave group' : 'Remove member'}
                  >
                    <UserMinus size={16} />
                  </button>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
