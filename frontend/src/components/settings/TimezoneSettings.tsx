import { useState, useEffect } from 'react';
import { Globe, Check, X, Loader2, AlertCircle } from 'lucide-react';
import { api } from '../../lib/api';

interface TimezoneSettingsProps {
  onClose: () => void;
}

// Common timezones grouped by region
const TIMEZONE_OPTIONS = [
  { label: 'UTC (Coordinated Universal Time)', value: 'UTC' },
  // Americas
  { label: 'US Eastern (New York)', value: 'America/New_York' },
  { label: 'US Central (Chicago)', value: 'America/Chicago' },
  { label: 'US Mountain (Denver)', value: 'America/Denver' },
  { label: 'US Pacific (Los Angeles)', value: 'America/Los_Angeles' },
  { label: 'US Alaska', value: 'America/Anchorage' },
  { label: 'US Hawaii', value: 'Pacific/Honolulu' },
  { label: 'Canada Atlantic (Halifax)', value: 'America/Halifax' },
  { label: 'Mexico City', value: 'America/Mexico_City' },
  { label: 'São Paulo', value: 'America/Sao_Paulo' },
  { label: 'Buenos Aires', value: 'America/Argentina/Buenos_Aires' },
  // Europe
  { label: 'London (GMT/BST)', value: 'Europe/London' },
  { label: 'Paris (CET)', value: 'Europe/Paris' },
  { label: 'Berlin', value: 'Europe/Berlin' },
  { label: 'Amsterdam', value: 'Europe/Amsterdam' },
  { label: 'Moscow', value: 'Europe/Moscow' },
  // Asia
  { label: 'Dubai', value: 'Asia/Dubai' },
  { label: 'Mumbai', value: 'Asia/Kolkata' },
  { label: 'Singapore', value: 'Asia/Singapore' },
  { label: 'Hong Kong', value: 'Asia/Hong_Kong' },
  { label: 'Tokyo', value: 'Asia/Tokyo' },
  { label: 'Seoul', value: 'Asia/Seoul' },
  { label: 'Shanghai', value: 'Asia/Shanghai' },
  // Oceania
  { label: 'Sydney', value: 'Australia/Sydney' },
  { label: 'Melbourne', value: 'Australia/Melbourne' },
  { label: 'Auckland', value: 'Pacific/Auckland' },
];

export function TimezoneSettings({ onClose }: TimezoneSettingsProps) {
  const [currentTimezone, setCurrentTimezone] = useState('UTC');
  const [selectedTimezone, setSelectedTimezone] = useState('UTC');
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  // Fetch current timezone on mount
  useEffect(() => {
    const fetchTimezone = async () => {
      try {
        const response = await api.getTimezone();
        setCurrentTimezone(response.timezone);
        setSelectedTimezone(response.timezone);
      } catch (err) {
        console.error('Failed to fetch timezone:', err);
        // Try to detect browser timezone as fallback
        const browserTz = Intl.DateTimeFormat().resolvedOptions().timeZone;
        setSelectedTimezone(browserTz || 'UTC');
      } finally {
        setIsLoading(false);
      }
    };
    fetchTimezone();
  }, []);

  const handleSave = async () => {
    if (selectedTimezone === currentTimezone) {
      setSuccess('No changes to save');
      return;
    }

    setIsSaving(true);
    setError(null);
    setSuccess(null);

    try {
      const result = await api.setTimezone(selectedTimezone);
      setCurrentTimezone(result.timezone);
      setSuccess('Timezone updated successfully');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save timezone');
    } finally {
      setIsSaving(false);
    }
  };

  const handleDetectTimezone = () => {
    const browserTz = Intl.DateTimeFormat().resolvedOptions().timeZone;
    if (browserTz) {
      setSelectedTimezone(browserTz);
      // Check if it's in our list
      const found = TIMEZONE_OPTIONS.find(tz => tz.value === browserTz);
      if (!found) {
        setError(`Detected timezone "${browserTz}" - you may need to select the closest match from the list`);
      }
    }
  };

  // Get current time in selected timezone for preview
  const getPreviewTime = () => {
    try {
      return new Date().toLocaleString('en-US', {
        timeZone: selectedTimezone,
        weekday: 'short',
        year: 'numeric',
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
        timeZoneName: 'short',
      });
    } catch {
      return 'Invalid timezone';
    }
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-white dark:bg-slate-800 rounded-xl shadow-xl max-w-md w-full">
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-slate-200 dark:border-slate-700">
          <div className="flex items-center gap-2">
            <Globe className="w-5 h-5 text-blue-500" />
            <h2 className="text-lg font-semibold text-slate-900 dark:text-white">
              Timezone Settings
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
              {/* Description */}
              <p className="text-sm text-slate-600 dark:text-slate-400">
                Set your timezone for accurate event times. Events will be displayed 
                in your local time.
              </p>

              {/* Timezone selector */}
              <div>
                <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">
                  Select Timezone
                </label>
                <select
                  value={selectedTimezone}
                  onChange={(e) => {
                    setSelectedTimezone(e.target.value);
                    setError(null);
                    setSuccess(null);
                  }}
                  className="w-full px-4 py-2 bg-slate-50 dark:bg-slate-900/50 border border-slate-300 dark:border-slate-600 rounded-lg text-slate-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                >
                  {TIMEZONE_OPTIONS.map((tz) => (
                    <option key={tz.value} value={tz.value}>
                      {tz.label}
                    </option>
                  ))}
                </select>
              </div>

              {/* Detect button */}
              <button
                onClick={handleDetectTimezone}
                className="text-sm text-blue-600 dark:text-blue-400 hover:underline"
              >
                Detect my timezone automatically
              </button>

              {/* Preview */}
              <div className="p-3 bg-slate-100 dark:bg-slate-700 rounded-lg">
                <p className="text-xs text-slate-500 dark:text-slate-400 mb-1">
                  Current time in selected timezone:
                </p>
                <p className="text-sm font-medium text-slate-900 dark:text-white">
                  {getPreviewTime()}
                </p>
              </div>

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
              <div className="flex items-center justify-end gap-2 pt-2">
                <button
                  onClick={onClose}
                  className="px-4 py-2 text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-700 rounded-lg transition-colors"
                >
                  Cancel
                </button>
                <button
                  onClick={handleSave}
                  disabled={isSaving || selectedTimezone === currentTimezone}
                  className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:bg-blue-400 text-white rounded-lg transition-colors"
                >
                  {isSaving ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : (
                    <Check className="w-4 h-4" />
                  )}
                  Save
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
