import { useEffect, useState, useRef, useCallback } from 'react';
import { MessageSquare, Users, LogOut, Shield, Settings, Key, ChevronDown, Share2, KeyRound, Globe, Menu, X, UserCircle, Activity, Calendar, FlaskConical, Gauge } from 'lucide-react';
import { ConversationList } from '../sidebar';
import { ChatContainer } from '../chat';
import { TracePanel } from '../trace';
import { ResearchList, ResearchView } from '../research';
import { EvalSidebar, EvalsView } from '../evals';
import { useResearch } from '../../hooks/useResearch';
import { ThemeToggle } from './ThemeToggle';
import { WrestlerPicker } from './WrestlerPicker';
import { LayoutToggle } from './LayoutToggle';
import { applyWrestler, getWrestler } from '../../lib/wrestlers';
import { GroupList, GroupChat, GroupMembers, CreateGroupModal } from '../groups';
import { UserManagement, ChangePassword, ApiKeySettings, TimezoneSettings, CalendarSettings } from '../settings';
import { KnowledgeGraph } from '../knowledge';
import { useChat } from '../../hooks/useChat';
import { useGroupWebSocket } from '../../hooks/useGroupWebSocket';
import { useThemeStore, applyTheme } from '../../stores/themeStore';
import { useGroupStore } from '../../stores/groupStore';
import { useAuthStore } from '../../stores/authStore';
import { api } from '../../lib/api';

type ViewMode = 'chats' | 'groups' | 'research' | 'evals';

export function AppLayout() {
  const { sendMessage, loadConversation, startNewConversation } = useChat();
  const research = useResearch();
  const theme = useThemeStore((state) => state.theme);
  const wrestlerChoice = useThemeStore((state) => state.wrestler);
  const wrestler = getWrestler(wrestlerChoice);
  const { user, logout } = useAuthStore();
  const [viewMode, setViewMode] = useState<ViewMode>(() => {
    try {
      const saved = localStorage.getItem('view-mode');
      return saved === 'groups' || saved === 'research' || saved === 'evals' ? saved : 'chats';
    } catch {
      return 'chats';
    }
  });
  const [showCreateGroup, setShowCreateGroup] = useState(false);
  const [showUserManagement, setShowUserManagement] = useState(false);
  const [showChangePassword, setShowChangePassword] = useState(false);
  const [showApiKeySettings, setShowApiKeySettings] = useState(false);
  const [showTimezoneSettings, setShowTimezoneSettings] = useState(false);
  const [showCalendarSettings, setShowCalendarSettings] = useState(false);
  const [showUserMenu, setShowUserMenu] = useState(false);
  const [showKnowledgeGraph, setShowKnowledgeGraph] = useState(false);
  const [showMobileSidebar, setShowMobileSidebar] = useState(false);
  const [showMobileMembers, setShowMobileMembers] = useState(false);
  const [showMobileTrace, setShowMobileTrace] = useState(false);
  const userMenuRef = useRef<HTMLDivElement>(null);
  
  // Close user menu when clicking outside
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (userMenuRef.current && !userMenuRef.current.contains(e.target as Node)) {
        setShowUserMenu(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);
  
  // Current user ID from auth
  const currentUserId = user?.id || '';
  
  // Group store
  const {
    groups,
    selectedGroupId,
    selectedGroup,
    selectedConversationId,
    selectedConversation,
    events,
    suggestions,
    fetchGroups,
    selectGroup,
    selectConversation,
    createConversation,
    addEvent,
    fetchEvents,
  } = useGroupStore();
  
  // Apply theme on mount
  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  useEffect(() => {
    applyWrestler(wrestlerChoice);
  }, [wrestlerChoice]);

  // Evals is superuser-only; anyone else who lands there goes back to chats
  useEffect(() => {
    if (viewMode === 'evals' && user && !user.is_superuser) setViewMode('chats');
  }, [viewMode, user]);

  // Remember the active tab so a reload lands where you were
  useEffect(() => {
    try { localStorage.setItem('view-mode', viewMode); } catch { /* storage unavailable */ }
  }, [viewMode]);
  
  // Fetch groups when switching to groups view
  useEffect(() => {
    if (viewMode === 'groups') {
      fetchGroups();
    }
  }, [viewMode, fetchGroups]);
  
  // Fetch events when a group is selected
  useEffect(() => {
    if (selectedGroupId) {
      fetchEvents();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedGroupId]);  // fetchEvents is stable from Zustand
  
  // Stable callback for event extraction - using ref to avoid re-renders
  const addEventRef = useRef(addEvent);
  addEventRef.current = addEvent;
  
  const handleEventExtracted = useCallback((event: Parameters<typeof addEvent>[0]) => {
    addEventRef.current(event);
  }, []);  // No dependencies - uses ref
  
  // WebSocket for group chat - only connect when viewing groups with valid selection
  const shouldConnectWS = viewMode === 'groups' && !!selectedGroupId && !!selectedConversationId;
  
  const {
    isConnected,
    messages: wsMessages,
    typingUsers,
    onlineUsers,
    agentStatus,
    streamingMessage,
    sendMessage: wsSendMessage,
    setTyping,
    error: wsError,
  } = useGroupWebSocket({
    groupId: shouldConnectWS ? selectedGroupId : '',
    conversationId: shouldConnectWS ? selectedConversationId : '',
    userId: currentUserId,
    onEventExtracted: handleEventExtracted,
  });
  
  // Combine conversation messages with real-time messages
  const groupMessages = selectedConversation
    ? [...selectedConversation.messages, ...wsMessages.filter(
        m => !selectedConversation.messages.some(cm => cm.id === m.id)
      )]
    : wsMessages;
  
  const handleSelectGroup = async (groupId: string) => {
    await selectGroup(groupId);
    // Fetch events for this group
    await fetchEvents();
    // Auto-select first conversation or create one
    const convs = await api.listGroupConversations(groupId);
    if (convs.length > 0) {
      await selectConversation(convs[0].id);
    } else {
      // Auto-create a conversation if none exists
      const newConv = await api.createGroupConversation(groupId);
      if (newConv) {
        await selectConversation(newConv.id);
      }
    }
  };
  
  const handleStartGroupConversation = async () => {
    if (!selectedGroupId) return;
    const conv = await createConversation();
    if (conv) {
      await selectConversation(conv.id);
    }
  };
  
  // Close mobile sidebar when selecting a conversation or group
  const handleMobileConversationSelect = (conversationId: string) => {
    loadConversation(conversationId);
    setShowMobileSidebar(false);
  };

  const handleMobileGroupSelect = async (groupId: string) => {
    await handleSelectGroup(groupId);
    setShowMobileSidebar(false);
  };

  const handleMobileNewConversation = () => {
    startNewConversation();
    setShowMobileSidebar(false);
  };

  const handleResearchSelect = (id: string) => {
    research.open(id);
    setShowMobileSidebar(false);
  };

  const handleResearchNew = () => {
    research.startNew();
    setShowMobileSidebar(false);
  };

  return (
    <div className={`app-shell flex overflow-hidden bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-100 ${wrestler ? 'wt-app' : ''}`}>
      {/* Mobile sidebar overlay */}
      {showMobileSidebar && (
        <div 
          className="fixed inset-0 bg-black/50 z-40 md:hidden"
          onClick={() => setShowMobileSidebar(false)}
        />
      )}
      
      {/* Sidebar - hidden on mobile, shown as overlay when toggled */}
      <div className={`
        fixed md:relative inset-y-0 left-0 z-50 wt-sidebar
        ${user?.is_superuser ? 'w-80' : 'w-72'} border-r border-slate-200 dark:border-slate-700 
        bg-slate-50 dark:bg-slate-800/50 flex flex-col h-full
        transform transition-transform duration-200 ease-in-out
        ${showMobileSidebar ? 'translate-x-0' : '-translate-x-full md:translate-x-0'}
      `}>
        {/* Mobile close button */}
        <div className="flex md:hidden items-center justify-between p-3 safe-area-inset-top border-b border-slate-200 dark:border-slate-700">
          <span className="font-semibold text-sm">Navigation</span>
          <button
            onClick={() => setShowMobileSidebar(false)}
            className="p-1 text-slate-600 dark:text-slate-400 hover:bg-slate-200 dark:hover:bg-slate-700 rounded"
          >
            <X size={20} />
          </button>
        </div>
        
        {/* View mode tabs */}
        <div className="flex shrink-0">
          <button
            onClick={() => setViewMode('chats')}
            className={`flex-1 flex items-center justify-center gap-1.5 px-1 py-3 text-[13px] font-medium transition-colors ${
              viewMode === 'chats'
                ? 'text-blue-600 dark:text-blue-400 border-b-2 border-blue-600 dark:border-blue-400'
                : 'text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 border-b-2 border-transparent'
            }`}
          >
            <MessageSquare size={18} />
            Chats
          </button>
          <button
            onClick={() => setViewMode('groups')}
            className={`flex-1 flex items-center justify-center gap-1.5 px-1 py-3 text-[13px] font-medium transition-colors ${
              viewMode === 'groups'
                ? 'text-blue-600 dark:text-blue-400 border-b-2 border-blue-600 dark:border-blue-400'
                : 'text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 border-b-2 border-transparent'
            }`}
          >
            <Users size={18} />
            Groups
          </button>
          <button
            onClick={() => setViewMode('research')}
            className={`flex-1 flex items-center justify-center gap-1.5 px-1 py-3 text-[13px] font-medium transition-colors ${
              viewMode === 'research'
                ? 'text-blue-600 dark:text-blue-400 border-b-2 border-blue-600 dark:border-blue-400'
                : 'text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 border-b-2 border-transparent'
            }`}
          >
            <FlaskConical size={18} />
            Research
          </button>
          {user?.is_superuser && (
            <button
              onClick={() => setViewMode('evals')}
              className={`flex-1 flex items-center justify-center gap-1.5 px-1 py-3 text-[13px] font-medium transition-colors ${
                viewMode === 'evals'
                  ? 'text-blue-600 dark:text-blue-400 border-b-2 border-blue-600 dark:border-blue-400'
                  : 'text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 border-b-2 border-transparent'
              }`}
            >
              <Gauge size={18} />
              Evals
            </button>
          )}
        </div>
        
        {/* Sidebar content */}
        <div className="flex-1 overflow-hidden flex flex-col">
          {viewMode === 'chats' ? (
            <ConversationList
              onNewConversation={handleMobileNewConversation}
              onSelectConversation={handleMobileConversationSelect}
              hideWrapper
            />
          ) : viewMode === 'evals' ? (
            <EvalSidebar onSelect={() => setShowMobileSidebar(false)} />
          ) : viewMode === 'research' ? (
            <ResearchList
              onNew={handleResearchNew}
              onSelect={handleResearchSelect}
              onDelete={research.remove}
            />
          ) : (
            <GroupList
              groups={groups}
              selectedGroupId={selectedGroupId}
              onSelectGroup={handleMobileGroupSelect}
              onCreateGroup={() => setShowCreateGroup(true)}
              onRefresh={fetchGroups}
            />
          )}
        </div>
      </div>
      
      {/* Main content area */}
      <div className="flex-1 flex flex-col min-w-0 wt-main">
        {/* Header */}
        <header className={`min-h-14 safe-area-inset-top border-b border-slate-200 dark:border-slate-700 flex items-center justify-between px-2 sm:px-4 shrink-0 ${wrestler ? 'wt-header' : ''}`}>
          <div className="flex items-center gap-2">
            {/* Mobile menu button */}
            <button
              onClick={() => setShowMobileSidebar(true)}
              className="p-2 md:hidden text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-700 rounded transition-colors"
            >
              <Menu size={20} />
            </button>
            <h1 className="font-semibold text-sm sm:text-base truncate">
              {viewMode === 'chats' ? 'Agent Chat' : viewMode === 'research' ? 'Deep Research' : viewMode === 'evals' ? 'Evals' : (selectedGroup?.name || 'Groups')}
            </h1>
            {wrestler && (
              <span className="hidden xl:inline text-xs wt-tagline truncate max-w-72">{wrestler.tagline}</span>
            )}
          </div>
          <div className="flex items-center gap-1 sm:gap-4">
            {viewMode === 'groups' && selectedGroup && !selectedConversationId && (
              <button
                onClick={handleStartGroupConversation}
                className="px-2 sm:px-3 py-1.5 text-xs sm:text-sm bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
              >
                <span className="hidden sm:inline">New Conversation</span>
                <span className="sm:hidden">New</span>
              </button>
            )}
            
            {/* Mobile trace toggle - only show in chat mode */}
            {viewMode === 'chats' && (
              <button
                onClick={() => setShowMobileTrace(!showMobileTrace)}
                className="p-2 lg:hidden text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-700 rounded transition-colors"
                title="Toggle Trace"
              >
                <Activity size={18} />
              </button>
            )}
            
            {/* Mobile members toggle - only show in group view with conversation */}
            {viewMode === 'groups' && selectedGroup && selectedConversationId && (
              <button
                onClick={() => setShowMobileMembers(!showMobileMembers)}
                className="p-2 md:hidden text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-700 rounded transition-colors"
                title="Toggle Members"
              >
                <UserCircle size={18} />
              </button>
            )}
            
            {/* User dropdown */}
            {user && (
              <div className="relative" ref={userMenuRef}>
                <button
                  onClick={() => setShowUserMenu(!showUserMenu)}
                  className="flex items-center gap-1 px-1 sm:px-2 py-1 text-sm text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-700 rounded transition-colors"
                >
                  {user.is_superuser && (
                    <Shield size={14} className="text-amber-500" />
                  )}
                  <span className="hidden sm:block max-w-32 truncate">{user.email}</span>
                  <ChevronDown size={14} />
                </button>
                
                {showUserMenu && (
                  <div className="absolute right-0 mt-1 w-48 bg-white dark:bg-gray-800 rounded-lg shadow-lg border dark:border-gray-700 py-1 z-50">
                    {/* Show email on mobile */}
                    <div className="sm:hidden px-3 py-2 text-xs text-slate-500 dark:text-slate-400 border-b dark:border-gray-700 truncate">
                      {user.email}
                    </div>
                    {user.is_superuser && (
                      <button
                        onClick={() => {
                          setShowUserManagement(true);
                          setShowUserMenu(false);
                        }}
                        className="w-full flex items-center gap-2 px-3 py-2 text-sm text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-gray-700"
                      >
                        <Settings size={16} />
                        Manage Users
                      </button>
                    )}
                    <button
                      onClick={() => {
                        setShowChangePassword(true);
                        setShowUserMenu(false);
                      }}
                      className="w-full flex items-center gap-2 px-3 py-2 text-sm text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-gray-700"
                    >
                      <Key size={16} />
                      Change Password
                    </button>
                    <button
                      onClick={() => {
                        setShowApiKeySettings(true);
                        setShowUserMenu(false);
                      }}
                      className="w-full flex items-center gap-2 px-3 py-2 text-sm text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-gray-700"
                    >
                      <KeyRound size={16} />
                      API Key Settings
                    </button>
                    <button
                      onClick={() => {
                        setShowTimezoneSettings(true);
                        setShowUserMenu(false);
                      }}
                      className="w-full flex items-center gap-2 px-3 py-2 text-sm text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-gray-700"
                    >
                      <Globe size={16} />
                      Timezone
                    </button>
                    <button
                      onClick={() => {
                        setShowCalendarSettings(true);
                        setShowUserMenu(false);
                      }}
                      className="w-full flex items-center gap-2 px-3 py-2 text-sm text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-gray-700"
                    >
                      <Calendar size={16} />
                      Google Calendar
                    </button>
                    <div className="border-t dark:border-gray-700 my-1" />
                    <button
                      onClick={() => {
                        logout();
                        window.location.reload();
                      }}
                      className="w-full flex items-center gap-2 px-3 py-2 text-sm text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20"
                    >
                      <LogOut size={16} />
                      Sign Out
                    </button>
                  </div>
                )}
              </div>
            )}
            
            <button
              onClick={() => setShowKnowledgeGraph(true)}
              className="hidden sm:inline-flex p-2 text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-700 rounded transition-colors"
              title="View Knowledge Graph"
            >
              <Share2 size={18} />
            </button>
            
            <WrestlerPicker />
            <LayoutToggle />
            <ThemeToggle />
          </div>
        </header>
        
        {/* Main content */}
        {viewMode === 'chats' ? (
          <ChatContainer onSendMessage={sendMessage} />
        ) : viewMode === 'evals' ? (
          <EvalsView />
        ) : viewMode === 'research' ? (
          <ResearchView
            onStart={research.start}
            onRerun={research.start}
            onRefreshDetail={research.open}
          />
        ) : selectedGroup && selectedConversationId ? (
          <div className="flex-1 flex overflow-hidden relative">
            <GroupChat
              group={selectedGroup}
              messages={groupMessages}
              typingUsers={typingUsers}
              onlineUsers={onlineUsers}
              onSendMessage={wsSendMessage}
              onTyping={setTyping}
              events={events}
              suggestions={suggestions}
              currentUserId={currentUserId}
              isConnected={isConnected}
              connectionError={wsError}
              agentStatus={agentStatus}
              streamingMessage={streamingMessage}
            />
            {/* Members panel - hidden on mobile, shown as overlay when toggled */}
            {showMobileMembers && (
              <div 
                className="fixed inset-0 bg-black/50 z-40 md:hidden"
                onClick={() => setShowMobileMembers(false)}
              />
            )}
            <div className={`
              fixed md:relative inset-y-0 right-0 z-50 md:z-auto
              w-72 border-l border-slate-200 dark:border-slate-700 shrink-0 overflow-y-auto
              bg-white dark:bg-slate-900 md:bg-transparent
              transform transition-transform duration-200 ease-in-out
              ${showMobileMembers ? 'translate-x-0' : 'translate-x-full md:translate-x-0'}
              hidden md:block ${showMobileMembers ? '!block' : ''}
            `}>
              {/* Mobile close button */}
              <div className="flex md:hidden items-center justify-between p-3 safe-area-inset-top border-b border-slate-200 dark:border-slate-700">
                <span className="font-semibold text-sm">Members</span>
                <button
                  onClick={() => setShowMobileMembers(false)}
                  className="p-1 text-slate-600 dark:text-slate-400 hover:bg-slate-200 dark:hover:bg-slate-700 rounded"
                >
                  <X size={20} />
                </button>
              </div>
              <GroupMembers
                groupId={selectedGroupId!}
                members={selectedGroup.members}
                currentUserId={currentUserId}
                createdBy={selectedGroup.created_by}
                onlineUsers={onlineUsers}
                onRefresh={() => selectGroup(selectedGroupId!)}
              />
            </div>
          </div>
        ) : selectedGroup ? (
          <div className="flex-1 flex flex-col md:flex-row">
            <div className="flex-1 flex items-center justify-center text-slate-500 dark:text-slate-400 p-4">
              <div className="text-center">
                <Users size={48} className="mx-auto mb-4 opacity-50" />
                <p>Select or start a conversation</p>
                <button
                  onClick={handleStartGroupConversation}
                  className="mt-4 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
                >
                  Start New Conversation
                </button>
              </div>
            </div>
            <div className="hidden md:block w-72 border-l border-slate-200 dark:border-slate-700">
              <GroupMembers
                groupId={selectedGroupId!}
                members={selectedGroup.members}
                currentUserId={currentUserId}
                createdBy={selectedGroup.created_by}
                onlineUsers={onlineUsers}
                onRefresh={() => selectGroup(selectedGroupId!)}
              />
            </div>
          </div>
        ) : (
          <div className="flex-1 flex items-center justify-center text-slate-500 dark:text-slate-400 p-4">
            <div className="text-center">
              <Users size={48} className="mx-auto mb-4 opacity-50" />
              <p>Select a group to start chatting</p>
              <button
                onClick={() => setShowCreateGroup(true)}
                className="mt-4 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
              >
                Create a Group
              </button>
            </div>
          </div>
        )}
      </div>
      
      {/* Trace panel - only show for individual chats */}
      {viewMode === 'chats' && (
        <>
          {/* Desktop trace panel */}
          <div className="hidden lg:block">
            <TracePanel />
          </div>
          
          {/* Mobile trace panel overlay */}
          {showMobileTrace && (
            <>
              <div 
                className="fixed inset-0 bg-black/50 z-40 lg:hidden"
                onClick={() => setShowMobileTrace(false)}
              />
              <div className="fixed inset-y-0 right-0 z-50 lg:hidden w-80 max-w-[85vw] bg-white dark:bg-slate-900 shadow-xl flex flex-col">
                <div className="flex items-center justify-between p-3 safe-area-inset-top border-b border-slate-200 dark:border-slate-700 shrink-0">
                  <span className="font-semibold text-sm flex items-center gap-2">
                    <Activity size={16} />
                    Workflow Trace
                  </span>
                  <button
                    onClick={() => setShowMobileTrace(false)}
                    className="p-2 text-slate-600 dark:text-slate-400 hover:bg-slate-200 dark:hover:bg-slate-700 rounded touch-manipulation"
                  >
                    <X size={20} />
                  </button>
                </div>
                <div className="flex-1 overflow-hidden">
                  <TracePanel embedded />
                </div>
              </div>
            </>
          )}
        </>
      )}
      
      {/* Create group modal */}
      <CreateGroupModal
        isOpen={showCreateGroup}
        onClose={() => setShowCreateGroup(false)}
        onCreated={fetchGroups}
      />
      
      {/* User management modal (admin only) */}
      {showUserManagement && (
        <UserManagement
          onClose={() => setShowUserManagement(false)}
          currentUserId={currentUserId}
        />
      )}
      
      {/* Change password modal */}
      {showChangePassword && (
        <ChangePassword onClose={() => setShowChangePassword(false)} />
      )}
      
      {/* API Key settings modal */}
      {showApiKeySettings && (
        <ApiKeySettings onClose={() => setShowApiKeySettings(false)} />
      )}
      
      {/* Timezone settings modal */}
      {showTimezoneSettings && (
        <TimezoneSettings onClose={() => setShowTimezoneSettings(false)} />
      )}
      
      {/* Calendar settings modal */}
      {showCalendarSettings && (
        <CalendarSettings onClose={() => setShowCalendarSettings(false)} />
      )}
      
      {/* Knowledge Graph modal */}
      <KnowledgeGraph
        isOpen={showKnowledgeGraph}
        onClose={() => setShowKnowledgeGraph(false)}
      />
    </div>
  );
}
