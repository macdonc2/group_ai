import { create } from 'zustand';
import { api } from '../lib/api';
import { useThemeStore } from './themeStore';
import type {
  IngredientGroup,
  PhotoCredit,
  PitchedCard,
  RecipeCard,
  RecipeDetail,
  RecipesStatus,
  RecipeUnit,
  UnitSystem,
} from '../types/recipes';

export type RecipeMode = 'find' | 'pitch';

export interface PitchForm {
  craving: string;
  have: string[];
  avoid: string[];
  count: number;
  allowNew: boolean;
  allowWeb: boolean;
}

interface RecipeState {
  status: RecipesStatus | null;
  mode: RecipeMode;
  saved: RecipeCard[];
  error: string | null;
  notice: string | null;

  // Find
  query: string;
  have: string[];
  category: string | null;
  results: RecipeCard[];
  searching: boolean;
  webResults: RecipeCard[];
  webBusy: boolean;
  /** The words the web was last searched for, so "nothing found" can be told from "not asked". */
  webSearched: string | null;
  importing: boolean;

  // Pitch
  form: PitchForm;
  pitching: boolean;
  activity: string | null;
  promo: string | null;
  cards: PitchedCard[];
  pitchedTitles: string[];

  // The open recipe
  openId: string | null;
  detail: RecipeDetail | null;
  loadingDetail: boolean;
  lines: IngredientGroup[];
  scale: string;
  system: UnitSystem;
  units: Record<number, RecipeUnit>;
  converting: boolean;
  credits: Record<string, PhotoCredit>;

  init: () => Promise<void>;
  setMode: (mode: RecipeMode) => void;
  setQuery: (query: string) => void;
  setHave: (have: string[]) => void;
  setCategory: (category: string | null) => void;
  runSearch: () => Promise<void>;
  searchWeb: () => Promise<void>;
  importUrl: (url: string) => Promise<void>;
  importCookbookFile: (file: File) => Promise<void>;
  setForm: (patch: Partial<PitchForm>) => void;
  pitch: (more?: boolean) => Promise<void>;
  open: (id: string) => Promise<void>;
  close: () => void;
  keep: (id: string) => Promise<void>;
  drop: (id: string) => Promise<void>;
  retryPicture: (id: string) => Promise<void>;
  setScale: (scale: string) => Promise<void>;
  setSystem: (system: UnitSystem) => Promise<void>;
  setLineUnit: (index: number, unit: RecipeUnit | null) => Promise<void>;
  dismiss: () => void;
}

function errorText(error: unknown, fallback: string): string {
  const raw = error instanceof Error ? error.message : '';
  try {
    const detail = JSON.parse(raw).detail;
    if (typeof detail === 'string') return detail;
  } catch {
    // not JSON
  }
  return raw && raw.length < 200 ? raw : fallback;
}

const TOOL_LABELS: Record<string, string> = {
  search_cookbook: 'Flipping through the cookbooks',
  search_web: 'Scouting the web',
};

const FORM_KEY = 'recipes-pitch-form';

function loadForm(): PitchForm {
  const blank: PitchForm = { craving: '', have: [], avoid: [], count: 3, allowNew: true, allowWeb: false };
  try {
    const stored = JSON.parse(localStorage.getItem(FORM_KEY) ?? 'null');
    // The avoid list and the kitchen are worth remembering between visits; the craving is not.
    if (stored && Array.isArray(stored.have) && Array.isArray(stored.avoid)) {
      return { ...blank, have: stored.have.slice(0, 30), avoid: stored.avoid.slice(0, 30) };
    }
  } catch {
    // storage unavailable or old format
  }
  return blank;
}

const pollers = new Map<string, ReturnType<typeof setTimeout>>();
let searchTicket = 0;
let convertTicket = 0;

export const useRecipeStore = create<RecipeState>((set, get) => {
  /** Put a fresher copy of one recipe everywhere it is shown. */
  const patch = (card: RecipeCard) => {
    const swap = <T extends RecipeCard>(list: T[]): T[] => list.map((c) => (c.id === card.id ? { ...c, ...card } : c));
    set((s) => ({
      results: swap(s.results),
      webResults: swap(s.webResults),
      cards: s.cards.map((c) => (c.id === card.id ? { ...c, ...card, hype: c.hype } : c)),
      saved: swap(s.saved),
      detail: s.detail && s.detail.id === card.id ? { ...s.detail, ...card } : s.detail,
    }));
  };

  const refreshSaved = async () => {
    try {
      set({ saved: await api.savedRecipes() });
    } catch {
      // the list is refreshed again on the next action
    }
  };

  // A picture is made after "keep" returns; poll that one recipe until it settles.
  const watchPicture = (id: string, attempt = 0) => {
    const running = pollers.get(id);
    if (running) clearTimeout(running);
    if (attempt > 90) return;
    pollers.set(id, setTimeout(async () => {
      try {
        const fresh = await api.getRecipe(id);
        patch(fresh);
        if (fresh.image_status === 'pending') watchPicture(id, attempt + 1);
        else pollers.delete(id);
      } catch {
        pollers.delete(id); // the recipe is gone
      }
    }, 2000));
  };

  const loadCredits = async (lines: IngredientGroup[]) => {
    const keys = [...new Set(lines.flatMap((g) => g.items.map((i) => i.photo)).filter((k): k is string => !!k))];
    const missing = keys.filter((k) => !get().credits[k]?.available);
    if (!missing.length || !get().status?.ingredient_photos) return;
    try {
      const found = await api.ingredientPhotoCredits(missing);
      set((s) => ({ credits: { ...s.credits, ...Object.fromEntries(found.map((c) => [c.key, c])) } }));
    } catch {
      // photos are decoration; lettered tiles stay
    }
  };

  const reconvert = async () => {
    const { openId, scale, system, units } = get();
    if (!openId) return;
    const ticket = ++convertTicket;
    set({ converting: true });
    try {
      const done = await api.convertRecipe(openId, scale, system, units);
      if (ticket === convertTicket && get().openId === openId) set({ lines: done.ingredients, converting: false });
    } catch (error) {
      if (ticket === convertTicket) set({ converting: false, error: errorText(error, 'Could not convert that.') });
    }
  };

  return {
    status: null,
    mode: 'find',
    saved: [],
    error: null,
    notice: null,
    query: '',
    have: [],
    category: null,
    results: [],
    searching: false,
    webResults: [],
    webBusy: false,
    webSearched: null,
    importing: false,
    form: loadForm(),
    pitching: false,
    activity: null,
    promo: null,
    cards: [],
    pitchedTitles: [],
    openId: null,
    detail: null,
    loadingDetail: false,
    lines: [],
    scale: '1',
    system: 'original',
    units: {},
    converting: false,
    credits: {},

    init: async () => {
      try {
        const [status, saved] = await Promise.all([api.recipesStatus(), api.savedRecipes()]);
        set({ status, saved });
        saved.filter((c) => c.image_status === 'pending').forEach((c) => watchPicture(c.id));
        await get().runSearch();
      } catch (error) {
        set({ error: errorText(error, 'Could not load the recipes.') });
      }
    },

    setMode: (mode) => set({ mode, openId: null, detail: null }),
    setQuery: (query) => set({ query }),
    setHave: (have) => set({ have }),
    setCategory: (category) => set({ category }),

    runSearch: async () => {
      const { query, have, category } = get();
      const ticket = ++searchTicket;
      set({ searching: true });
      try {
        const results = await api.searchRecipes(query, have, category);
        if (ticket === searchTicket) set({ results, searching: false });
      } catch (error) {
        if (ticket === searchTicket) set({ searching: false, error: errorText(error, 'The search failed.') });
      }
    },

    searchWeb: async () => {
      const query = get().query.trim();
      if (query.length < 2 || get().webBusy) return;
      set({ webBusy: true, error: null });
      try {
        set({ webResults: await api.searchWebRecipes(query), webBusy: false, webSearched: query });
      } catch (error) {
        set({ webBusy: false, error: errorText(error, 'The web lookup failed.') });
      }
    },

    importUrl: async (url) => {
      if (!url.trim() || get().webBusy) return;
      set({ webBusy: true, error: null });
      try {
        const found = await api.importWebRecipe(url.trim());
        set((s) => ({
          webBusy: false,
          webSearched: s.webSearched ?? url.trim(),
          webResults: [...found, ...s.webResults.filter((c) => !found.some((f) => f.id === c.id))],
        }));
      } catch (error) {
        set({ webBusy: false, error: errorText(error, 'That page could not be read.') });
      }
    },

    importCookbookFile: async (file) => {
      set({ importing: true, error: null, notice: null });
      try {
        const result = await api.importCookbooks(JSON.parse(await file.text()));
        const skipped = result.skipped.length ? ` ${result.skipped.length} could not be read and were skipped.` : '';
        set({
          importing: false,
          notice: `${result.added} recipes added, ${result.updated} updated. ${result.total} in your cookbooks.${skipped}`,
        });
        set({ status: await api.recipesStatus() });
        await get().runSearch();
      } catch (error) {
        const bad = error instanceof SyntaxError;
        set({
          importing: false,
          error: bad ? 'That file is not JSON.' : errorText(error, 'That file is not a cookbook file this app can read.'),
        });
      }
    },

    setForm: (patchForm) => {
      const form = { ...get().form, ...patchForm };
      set({ form });
      try {
        localStorage.setItem(FORM_KEY, JSON.stringify({ have: form.have, avoid: form.avoid }));
      } catch {
        // storage unavailable
      }
    },

    pitch: async (more = false) => {
      if (get().pitching) return;
      const { form } = get();
      const already = more ? get().pitchedTitles : [];
      const wrestler = useThemeStore.getState().wrestler;
      set({ pitching: true, activity: 'Warming up', error: null, ...(more ? {} : { promo: null, cards: [], pitchedTitles: [] }) });
      let failure: string | null = null;
      let gotCard = false;
      try {
        await api.streamRecipePitch(
          {
            craving: form.craving.trim(),
            have: form.have,
            avoid: form.avoid,
            already_pitched: already.slice(-40),
            count: form.count,
            allow_new: form.allowNew,
            allow_web: form.allowWeb,
            persona: wrestler !== 'none' ? wrestler : undefined,
          },
          (event) => {
            if (event.event_type === 'tool_result') {
              set({ activity: TOOL_LABELS[String(event.data?.tool_name ?? '')] ?? 'Working the crowd' });
            } else if (event.event_type === 'pitch') {
              gotCard = true;
              const cards = event.data?.cards ?? [];
              set((s) => ({
                promo: event.data?.promo ?? '',
                cards,
                pitchedTitles: [...s.pitchedTitles, ...cards.map((c) => c.title)],
              }));
            } else if (event.event_type === 'error') {
              failure = event.message;
            }
          },
        );
      } catch (error) {
        failure = errorText(error, 'The connection was lost. Please try again.');
      }
      set({ pitching: false, activity: null, error: gotCard ? null : failure ?? 'No card came back. Please try again.' });
    },

    open: async (id) => {
      set({ openId: id, detail: null, lines: [], loadingDetail: true, scale: '1', system: 'original', units: {}, error: null });
      try {
        const detail = await api.getRecipe(id);
        if (get().openId !== id) return;
        set({ detail, lines: detail.ingredients, loadingDetail: false });
        if (detail.image_status === 'pending') watchPicture(id);
        void loadCredits(detail.ingredients);
      } catch (error) {
        if (get().openId === id) {
          set({ openId: null, loadingDetail: false, error: errorText(error, 'That recipe could not be opened.') });
        }
      }
    },

    close: () => set({ openId: null, detail: null, lines: [] }),

    keep: async (id) => {
      set({ error: null });
      try {
        const kept = await api.keepRecipe(id);
        patch(kept);
        await refreshSaved();
        if (kept.image_status === 'pending') watchPicture(id);
      } catch (error) {
        set({ error: errorText(error, 'Could not add that to your list.') });
      }
    },

    drop: async (id) => {
      set({ error: null });
      try {
        const card = [...get().saved, ...get().results, ...get().cards, ...get().webResults].find((c) => c.id === id)
          ?? get().detail;
        await api.dropRecipe(id);
        if (card && card.source !== 'cookbook') {
          // A model-written or web recipe is deleted outright when it leaves the list.
          set((s) => ({
            results: s.results.filter((c) => c.id !== id),
            webResults: s.webResults.filter((c) => c.id !== id),
            cards: s.cards.filter((c) => c.id !== id),
            ...(s.openId === id ? { openId: null, detail: null, lines: [] } : {}),
          }));
        } else if (card) {
          patch({ ...card, saved: false });
        }
        await refreshSaved();
      } catch (error) {
        set({ error: errorText(error, 'Could not take that off your list.') });
      }
    },

    retryPicture: async (id) => {
      try {
        patch(await api.retryRecipePicture(id));
        watchPicture(id);
      } catch (error) {
        set({ error: errorText(error, 'Could not ask for the picture.') });
      }
    },

    setScale: async (scale) => {
      set({ scale });
      await reconvert();
    },

    setSystem: async (system) => {
      set({ system, units: {} }); // a new system starts every line from that system's own choice
      await reconvert();
    },

    setLineUnit: async (index, unit) => {
      const units = { ...get().units };
      if (unit) units[index] = unit;
      else delete units[index];
      set({ units });
      await reconvert();
    },

    dismiss: () => set({ error: null, notice: null }),
  };
});
