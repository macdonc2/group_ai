import { useEffect, useState } from 'react';
import { api } from '../../lib/api';

// Pictures are fetched from our own API with the Authorization header and shown as blob:
// addresses (allowed by the page's image policy). One fetch per path per page load.
const ready = new Map<string, string>();
const inFlight = new Map<string, Promise<string | null>>();

function load(path: string): Promise<string | null> {
  const known = ready.get(path);
  if (known) return Promise.resolve(known);
  let request = inFlight.get(path);
  if (!request) {
    request = api
      .fetchImage(path)
      .then((blob) => {
        if (!blob || !blob.type.startsWith('image/')) return null;
        const address = URL.createObjectURL(blob);
        ready.set(path, address);
        return address;
      })
      .catch(() => null)
      .finally(() => inFlight.delete(path));
    inFlight.set(path, request);
  }
  return request;
}

/** The blob: address of a picture served by the API, or null while loading or when there is none. */
export function useApiImage(path: string | null): string | null {
  const [state, setState] = useState<{ path: string | null; address: string | null }>({ path: null, address: null });
  useEffect(() => {
    if (!path) return;
    let live = true;
    load(path).then((address) => {
      if (live) setState({ path, address });
    });
    return () => {
      live = false;
    };
  }, [path]);
  if (!path) return null;
  return ready.get(path) ?? (state.path === path ? state.address : null);
}
