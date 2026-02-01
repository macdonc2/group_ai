import { useState, useEffect } from 'react';
import { Calendar, Check, X, Loader2, AlertCircle, Link2, Unlink, ChevronDown } from 'lucide-react';
import { api } from '../../lib/api';

interface CalendarSettingsProps {
  onClose: () => void;
}

interface CalendarInfo {
  id: string;
  name: string;
  is_primary: boolean;
}

interface CalendarStatus {
  connected: boolean;
  email: string | null;
  calendar_enabled: boolean;
  selected_calendar_id: string | null;
  sync_confirmed_only: boolean;
}

export function CalendarSettings({ onClose }: CalendarSettingsProps) {
  const [status, setStatus] = useState<CalendarStatus | null>(null);
  const [calendars, setCalendars] = useState<CalendarInfo[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isConnecting, setIsConnecting] = useState(false);
  const [isDisconnecting, setIsDisconnecting] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [showCalendarDropdown, setShowCalendarDropdown] = useState(false);

  // Check current status on mount
  useEffect(() => {
    const checkStatus = async () => {
      try {
        const currentStatus = await api.getCalendarStatus();
        setStatus(currentStatus);
        
        // If connected, fetch available calendars
        if (currentStatus.connected) {
          try {
            const calendarList = await api.getCalendars();
            setCalendars(calendarList);
          } catch {
            // Calendars might fail if token expired
            console.error('Failed to fetch calendars');
          }
        }
      } catch (err) {
        console.error('Failed to check calendar status:', err);
        setError('Failed to load calendar settings');
      } finally {
        setIsLoading(false);
      }
    };
    checkStatus();
  }, []);

  const handleConnect = async () => {
    setIsConnecting(true);
    setError(null);
    
    // Open popup immediately (must be synchronous to avoid popup blocker)
    const popup = window.open('about:blank', '_blank', 'width=600,height=700');
    
    try {
      const { authorization_url } = await api.connectCalendar();
      // Navigate the already-open popup to the OAuth URL
      if (popup) {
        popup.location.href = authorization_url;
      } else {
        // Popup was blocked, fallback to redirect
        window.location.href = authorization_url;
      }
      
      // Start polling for connection status
      const pollInterval = setInterval(async () => {
        try {
          const newStatus = await api.getCalendarStatus();
          if (newStatus.connected) {
            clearInterval(pollInterval);
            setStatus(newStatus);
            setSuccess('Google Calendar connected successfully!');
            setIsConnecting(false);
            
            // Fetch calendars
            const calendarList = await api.getCalendars();
            setCalendars(calendarList);
          }
        } catch {
          // Keep polling
        }
      }, 2000);
      
      // Stop polling after 5 minutes
      setTimeout(() => {
        clearInterval(pollInterval);
        setIsConnecting(false);
      }, 300000);
    } catch (err) {
      // Close the popup on error
      if (popup && !popup.closed) {
        popup.close();
      }
      setError(err instanceof Error ? err.message : 'Failed to initiate connection');
      setIsConnecting(false);
    }
  };

  const handleDisconnect = async () => {
    if (!confirm('Disconnect Google Calendar? Your events will no longer sync.')) {
      return;
    }
    
    setIsDisconnecting(true);
    setError(null);
    setSuccess(null);
    
    try {
      await api.disconnectCalendar();
      setStatus({
        connected: false,
        email: null,
        calendar_enabled: false,
        selected_calendar_id: null,
        sync_confirmed_only: false,
      });
      setCalendars([]);
      setSuccess('Google Calendar disconnected');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to disconnect');
    } finally {
      setIsDisconnecting(false);
    }
  };

  const handleToggleEnabled = async () => {
    if (!status) return;
    
    setIsSaving(true);
    setError(null);
    
    try {
      await api.updateCalendarSettings({ calendar_enabled: !status.calendar_enabled });
      setStatus({ ...status, calendar_enabled: !status.calendar_enabled });
      setSuccess(status.calendar_enabled ? 'Calendar sync disabled' : 'Calendar sync enabled');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to update settings');
    } finally {
      setIsSaving(false);
    }
  };

  const handleSelectCalendar = async (calendarId: string | null) => {
    if (!status) return;
    
    setIsSaving(true);
    setError(null);
    setShowCalendarDropdown(false);
    
    try {
      await api.updateCalendarSettings({ selected_calendar_id: calendarId });
      setStatus({ ...status, selected_calendar_id: calendarId });
      setSuccess(calendarId ? 'Calendar selected' : 'Using primary calendar');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to update calendar');
    } finally {
      setIsSaving(false);
    }
  };

  const handleToggleSyncConfirmedOnly = async () => {
    if (!status) return;
    
    setIsSaving(true);
    setError(null);
    
    try {
      await api.updateCalendarSettings({ sync_confirmed_only: !status.sync_confirmed_only });
      setStatus({ ...status, sync_confirmed_only: !status.sync_confirmed_only });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to update settings');
    } finally {
      setIsSaving(false);
    }
  };

  const getSelectedCalendarName = () => {
    if (!status?.selected_calendar_id) {
      const primary = calendars.find(c => c.is_primary);
      return primary ? `${primary.name} (Primary)` : 'Primary Calendar';
    }
    const selected = calendars.find(c => c.id === status.selected_calendar_id);
    return selected?.name || 'Selected Calendar';
  };

  // Clear success message after 3 seconds
  useEffect(() => {
    if (success) {
      const timer = setTimeout(() => setSuccess(null), 3000);
      return () => clearTimeout(timer);
    }
  }, [success]);

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-white dark:bg-slate-800 rounded-xl shadow-xl max-w-md w-full">
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-slate-200 dark:border-slate-700">
          <div className="flex items-center gap-2">
            <Calendar className="w-5 h-5 text-blue-500" />
            <h2 className="text-lg font-semibold text-slate-900 dark:text-white">
              Google Calendar
            </h2>
          </div>
          <button
            onClick={onClose}
            className="p-1 hover:bg-slate-100 dark:hover:bg-slate-700 rounded transition-colors"
          >
            <X className="w-5 h-5 text-slate-500" />
          </button>
        </div>

        {/* Content */}
        <div className="p-4 space-y-4">
          {isLoading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="w-6 h-6 animate-spin text-blue-500" />
            </div>
          ) : (
            <>
              {/* Connection Status */}
              <div className={`flex items-center gap-2 p-3 rounded-lg ${
                status?.connected 
                  ? 'bg-green-50 dark:bg-green-900/20 text-green-700 dark:text-green-300'
                  : 'bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-300'
              }`}>
                {status?.connected ? (
                  <>
                    <Link2 className="w-5 h-5" />
                    <div className="flex-1">
                      <span className="block">Connected to Google Calendar</span>
                      {status.email && (
                        <span className="text-sm opacity-75">{status.email}</span>
                      )}
                    </div>
                  </>
                ) : (
                  <>
                    <AlertCircle className="w-5 h-5" />
                    <span>Not connected to Google Calendar</span>
                  </>
                )}
              </div>

              {/* Description */}
              <p className="text-sm text-slate-600 dark:text-slate-400">
                {status?.connected 
                  ? 'Your events can be synced with Google Calendar. Events you create here will appear in your calendar, and vice versa.'
                  : 'Connect your Google Calendar to sync events. Events mentioned in conversations can be automatically added to your calendar.'}
              </p>

              {/* Connected State */}
              {status?.connected && (
                <div className="space-y-4">
                  {/* Enable/Disable Toggle */}
                  <div className="flex items-center justify-between p-3 bg-slate-50 dark:bg-slate-900/50 rounded-lg">
                    <div>
                      <span className="block text-sm font-medium text-slate-700 dark:text-slate-300">
                        Calendar Sync
                      </span>
                      <span className="text-xs text-slate-500 dark:text-slate-400">
                        Automatically sync events
                      </span>
                    </div>
                    <button
                      onClick={handleToggleEnabled}
                      disabled={isSaving}
                      className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                        status.calendar_enabled 
                          ? 'bg-blue-600' 
                          : 'bg-slate-300 dark:bg-slate-600'
                      }`}
                    >
                      <span
                        className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                          status.calendar_enabled ? 'translate-x-6' : 'translate-x-1'
                        }`}
                      />
                    </button>
                  </div>

                  {/* Calendar Picker */}
                  <div className="relative">
                    <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">
                      Calendar
                    </label>
                    <button
                      onClick={() => setShowCalendarDropdown(!showCalendarDropdown)}
                      disabled={isSaving}
                      className="w-full flex items-center justify-between px-4 py-2 bg-slate-50 dark:bg-slate-900/50 border border-slate-300 dark:border-slate-600 rounded-lg text-slate-900 dark:text-white"
                    >
                      <span>{getSelectedCalendarName()}</span>
                      <ChevronDown className="w-4 h-4 text-slate-500" />
                    </button>
                    
                    {showCalendarDropdown && (
                      <div className="absolute z-10 mt-1 w-full bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-600 rounded-lg shadow-lg max-h-48 overflow-auto">
                        <button
                          onClick={() => handleSelectCalendar(null)}
                          className="w-full text-left px-4 py-2 hover:bg-slate-100 dark:hover:bg-slate-700 text-sm"
                        >
                          Use Primary Calendar
                        </button>
                        {calendars.map((cal) => (
                          <button
                            key={cal.id}
                            onClick={() => handleSelectCalendar(cal.id)}
                            className={`w-full text-left px-4 py-2 hover:bg-slate-100 dark:hover:bg-slate-700 text-sm ${
                              status.selected_calendar_id === cal.id 
                                ? 'bg-blue-50 dark:bg-blue-900/20' 
                                : ''
                            }`}
                          >
                            {cal.name}
                            {cal.is_primary && (
                              <span className="ml-2 text-xs text-slate-500">(Primary)</span>
                            )}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>

                  {/* Sync Confirmed Only */}
                  <div className="flex items-center justify-between p-3 bg-slate-50 dark:bg-slate-900/50 rounded-lg">
                    <div>
                      <span className="block text-sm font-medium text-slate-700 dark:text-slate-300">
                        Only Sync Confirmed Events
                      </span>
                      <span className="text-xs text-slate-500 dark:text-slate-400">
                        Skip tentative or unconfirmed events
                      </span>
                    </div>
                    <button
                      onClick={handleToggleSyncConfirmedOnly}
                      disabled={isSaving}
                      className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                        status.sync_confirmed_only 
                          ? 'bg-blue-600' 
                          : 'bg-slate-300 dark:bg-slate-600'
                      }`}
                    >
                      <span
                        className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                          status.sync_confirmed_only ? 'translate-x-6' : 'translate-x-1'
                        }`}
                      />
                    </button>
                  </div>
                </div>
              )}

              {/* Error/Success messages */}
              {error && (
                <div className="flex items-center gap-2 p-3 bg-red-50 dark:bg-red-900/20 text-red-700 dark:text-red-300 rounded-lg text-sm">
                  <AlertCircle className="w-4 h-4 shrink-0" />
                  <span>{error}</span>
                </div>
              )}
              {success && (
                <div className="flex items-center gap-2 p-3 bg-green-50 dark:bg-green-900/20 text-green-700 dark:text-green-300 rounded-lg text-sm">
                  <Check className="w-4 h-4 shrink-0" />
                  <span>{success}</span>
                </div>
              )}

              {/* Actions */}
              <div className="flex items-center justify-between pt-2">
                {status?.connected ? (
                  <button
                    onClick={handleDisconnect}
                    disabled={isDisconnecting}
                    className="flex items-center gap-2 px-3 py-2 text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 rounded-lg transition-colors text-sm"
                  >
                    {isDisconnecting ? (
                      <Loader2 className="w-4 h-4 animate-spin" />
                    ) : (
                      <Unlink className="w-4 h-4" />
                    )}
                    Disconnect
                  </button>
                ) : (
                  <div />
                )}
                <div className="flex items-center gap-2 ml-auto">
                  <button
                    onClick={onClose}
                    className="px-4 py-2 text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-700 rounded-lg transition-colors"
                  >
                    {status?.connected ? 'Done' : 'Cancel'}
                  </button>
                  {!status?.connected && (
                    <button
                      onClick={handleConnect}
                      disabled={isConnecting}
                      className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:bg-blue-400 text-white rounded-lg transition-colors"
                    >
                      {isConnecting ? (
                        <>
                          <Loader2 className="w-4 h-4 animate-spin" />
                          Waiting...
                        </>
                      ) : (
                        <>
                          <Link2 className="w-4 h-4" />
                          Connect Calendar
                        </>
                      )}
                    </button>
                  )}
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
