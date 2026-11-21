import { useMemo } from 'react';
import { MapPin } from 'lucide-react';
import { mapEmbedUrl, mapPlaces } from '../../lib/maps';

/** An embedded map for each place a message links to with a show_map link. */
export function MapEmbeds({ text }: { text: string }) {
  const places = useMemo(() => mapPlaces(text), [text]);
  if (places.length === 0) return null;
  return (
    <div className="mt-3 space-y-3">
      {places.map((place) => (
        <figure
          key={place}
          className="overflow-hidden rounded-lg border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-900"
        >
          <iframe
            title={`Map of ${place}`}
            src={mapEmbedUrl(place)}
            loading="lazy"
            referrerPolicy="no-referrer"
            sandbox="allow-scripts allow-same-origin allow-popups allow-popups-to-escape-sandbox"
            className="block w-full h-56 sm:h-72 border-0"
          />
          <figcaption className="flex items-center gap-1.5 px-3 py-1.5 text-xs text-slate-600 dark:text-slate-300">
            <MapPin className="w-3.5 h-3.5 shrink-0" />
            <span className="truncate">{place}</span>
          </figcaption>
        </figure>
      ))}
    </div>
  );
}
