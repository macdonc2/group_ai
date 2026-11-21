// Map links the backend's show_map tool puts in a reply (src/agent_system/adapters/outbound/llm/maps.py).
// Only this exact link shape is recognised, and only the place text is taken from it: the frame's
// address is built here, so reply text can never choose what the frame loads.

const MAP_LINK_PREFIX = 'https://www.google.com/maps/search/?api=1&query=';
const MAP_LINK = /https:\/\/www\.google\.com\/maps\/search\/\?api=1&query=[^\s)>\]"'<]+/g;
const MAX_MAPS = 3;
const MAX_PLACE_CHARS = 200;

/** The places a message links to on the map, in order, without repeats. */
export function mapPlaces(text: string): string[] {
  const places: string[] = [];
  const seen = new Set<string>();
  for (const link of text.match(MAP_LINK) ?? []) {
    let place: string;
    try {
      const encoded = link.slice(MAP_LINK_PREFIX.length).split('&')[0].replace(/[.,;:!?]+$/, '');
      place = decodeURIComponent(encoded.replace(/\+/g, ' ')).replace(/\s+/g, ' ').trim();
    } catch {
      continue; // a cut-off link while the reply is still streaming
    }
    const key = place.toLowerCase();
    if (!place || place.length > MAX_PLACE_CHARS || seen.has(key)) continue;
    seen.add(key);
    places.push(place);
    if (places.length === MAX_MAPS) break;
  }
  return places;
}

export function mapEmbedUrl(place: string): string {
  return `https://www.google.com/maps?q=${encodeURIComponent(place)}&output=embed`;
}
