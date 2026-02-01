import { useState } from 'react';
import { Users, Plus, ChevronRight, Trash2 } from 'lucide-react';
import type { Group } from '../../types';
import { api } from '../../lib/api';

interface GroupListProps {
  groups: Group[];
  selectedGroupId: string | null;
  onSelectGroup: (groupId: string) => void;
  onCreateGroup: () => void;
  onRefresh: () => void;
}

export function GroupList({
  groups,
  selectedGroupId,
  onSelectGroup,
  onCreateGroup,
  onRefresh,
}: GroupListProps) {
  const [isDeleting, setIsDeleting] = useState<string | null>(null);

  const handleDelete = async (e: React.MouseEvent, groupId: string) => {
    e.stopPropagation();
    
    const confirmed = window.confirm('Delete this group? This cannot be undone.');
    if (!confirmed) return;

    setIsDeleting(groupId);
    try {
      await api.deleteGroup(groupId);
      onRefresh();
    } catch (error) {
      console.error('Failed to delete group:', error);
      alert('Cannot delete group. Make sure all other members have left first.');
    } finally {
      setIsDeleting(null);
    }
  };

  return (
    <div className="flex flex-col h-full">
      <div className="p-4 border-b border-gray-200 dark:border-gray-700">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">
            Groups
          </h2>
          <button
            onClick={onCreateGroup}
            className="p-2 text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg transition-colors"
            title="Create new group"
          >
            <Plus size={20} />
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto">
        {groups.length === 0 ? (
          <div className="p-4 text-center text-gray-500 dark:text-gray-400">
            <Users className="mx-auto mb-2" size={24} />
            <p className="text-sm">No groups yet</p>
            <button
              onClick={onCreateGroup}
              className="mt-2 text-sm text-blue-600 dark:text-blue-400 hover:underline"
            >
              Create your first group
            </button>
          </div>
        ) : (
          <div className="p-2 space-y-1">
            {groups.map((group) => (
              <div
                key={group.id}
                onClick={() => onSelectGroup(group.id)}
                className={`
                  flex items-center justify-between p-3 rounded-lg cursor-pointer
                  transition-colors group/item
                  ${
                    selectedGroupId === group.id
                      ? 'bg-blue-50 dark:bg-blue-900/30 border border-blue-200 dark:border-blue-800'
                      : 'hover:bg-gray-50 dark:hover:bg-gray-700/50'
                  }
                `}
              >
                <div className="flex items-center min-w-0 flex-1">
                  <div className="flex-shrink-0 w-10 h-10 bg-gradient-to-br from-blue-500 to-purple-500 rounded-full flex items-center justify-center">
                    <Users className="text-white" size={18} />
                  </div>
                  <div className="ml-3 min-w-0">
                    <p className="text-sm font-medium text-gray-900 dark:text-gray-100 truncate">
                      {group.name}
                    </p>
                    <p className="text-xs text-gray-500 dark:text-gray-400">
                      {group.member_count} member{group.member_count !== 1 ? 's' : ''}
                    </p>
                  </div>
                </div>
                <div className="flex items-center">
                  <button
                    onClick={(e) => handleDelete(e, group.id)}
                    disabled={isDeleting === group.id}
                    className="p-1.5 text-gray-400 hover:text-red-500 rounded opacity-0 group-hover/item:opacity-100 transition-opacity"
                  >
                    <Trash2 size={14} />
                  </button>
                  <ChevronRight className="text-gray-400 ml-1" size={16} />
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
