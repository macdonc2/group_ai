import { useEffect, useRef, useState } from 'react';
import { BookUp, Globe, Link2, Loader2, Search } from 'lucide-react';
import { useRecipeStore } from '../../stores/recipeStore';
import { ChipInput } from './parts';
import { RecipeTile } from './RecipeTile';

/** Find: search the person's cookbooks and saved recipes in code, and optionally scout the web. */
export function FindPanel() {
  const status = useRecipeStore((s) => s.status);
  const query = useRecipeStore((s) => s.query);
  const have = useRecipeStore((s) => s.have);
  const category = useRecipeStore((s) => s.category);
  const results = useRecipeStore((s) => s.results);
  const searching = useRecipeStore((s) => s.searching);
  const webResults = useRecipeStore((s) => s.webResults);
  const webBusy = useRecipeStore((s) => s.webBusy);
  const webSearched = useRecipeStore((s) => s.webSearched);
  const importing = useRecipeStore((s) => s.importing);
  const setQuery = useRecipeStore((s) => s.setQuery);
  const setHave = useRecipeStore((s) => s.setHave);
  const setCategory = useRecipeStore((s) => s.setCategory);
  const runSearch = useRecipeStore((s) => s.runSearch);
  const searchWeb = useRecipeStore((s) => s.searchWeb);
  const importUrl = useRecipeStore((s) => s.importUrl);
  const importCookbookFile = useRecipeStore((s) => s.importCookbookFile);
  const [url, setUrl] = useState('');
  const filePicker = useRef<HTMLInputElement>(null);

  // Search as the person types, a beat after they stop.
  useEffect(() => {
    const timer = setTimeout(() => { void runSearch(); }, 220);
    return () => clearTimeout(timer);
  }, [query, have, category, runSearch]);

  const noCookbooks = status !== null && status.cookbook_recipes === 0;
  const filtering = Boolean(query.trim() || have.length || category);

  return (
    <div className="space-y-5">
      <div className="grid gap-4 lg:grid-cols-2">
        <div>
          <label htmlFor="rk-find" className="rk-label block mb-1">Call out a dish</label>
          <div className="relative">
            <input
              id="rk-find"
              className="rk-input pr-10"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="tacos, chicken spaghetti, something with shrimp…"
              maxLength={200}
            />
            <span className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500">
              {searching ? <Loader2 size={18} className="animate-spin" /> : <Search size={18} />}
            </span>
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <label htmlFor="rk-category" className="rk-kicker">Division</label>
            <select
              id="rk-category"
              className="rk-unit !max-w-none !text-sm !py-1.5"
              value={category ?? ''}
              onChange={(e) => setCategory(e.target.value || null)}
            >
              <option value="">All of them</option>
              {(status?.categories ?? []).map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
          </div>
        </div>
        <ChipInput
          id="rk-find-have"
          label="In my corner"
          hint="Ingredients you have. Recipes that use more of them rank higher."
          values={have}
          onChange={setHave}
          placeholder="shrimp, lime, coconut milk…  (Enter to add)"
        />
      </div>

      {noCookbooks && (
        <div className="rk-card p-4 flex flex-wrap items-center gap-4">
          <div className="rk-burst shrink-0">No<br />roster<br />yet!</div>
          <div className="flex-1 min-w-[14rem]">
            <h3 className="rk-display text-2xl">Your cookbooks are not loaded</h3>
            <p className="text-sm mt-1">
              Load your cookbook file (the JSON made from your cookbooks). It goes into your own library: nobody
              else who uses this app can see it.
            </p>
          </div>
          <button type="button" className="rk-btn" disabled={importing} onClick={() => filePicker.current?.click()}>
            {importing ? <Loader2 size={18} className="animate-spin" /> : <BookUp size={18} />} Load cookbook file
          </button>
        </div>
      )}
      <input
        ref={filePicker}
        type="file"
        accept="application/json,.json"
        className="hidden"
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) void importCookbookFile(file);
          e.target.value = '';
        }}
      />

      <section aria-label="Results">
        <div className="flex items-baseline justify-between gap-3 mb-3">
          <h2 className="rk-title text-3xl">{filtering ? 'The contenders' : 'The whole roster'}</h2>
          <p className="rk-muted text-sm">
            {results.length} {results.length === 1 ? 'recipe' : 'recipes'}
            {!noCookbooks && status && (
              <>
                {' · '}
                <button type="button" className="underline" onClick={() => filePicker.current?.click()} disabled={importing}>
                  {importing ? 'loading…' : 'reload cookbook file'}
                </button>
              </>
            )}
          </p>
        </div>
        {results.length === 0 ? (
          <p className="rk-muted">
            {filtering
              ? 'Nobody answered the bell for that one. Try other words, fewer ingredients, or scout the web below.'
              : noCookbooks ? 'Nothing here yet.' : 'No recipes.'}
          </p>
        ) : (
          <div className="grid gap-5 sm:grid-cols-2 xl:grid-cols-3">
            {results.map((card, i) => <RecipeTile key={card.id} card={card} alt={i % 2 === 1} />)}
          </div>
        )}
      </section>

      <section aria-label="From the web" className="pt-2">
        <div className="rk-ropes mb-4" aria-hidden="true" />
        <h2 className="rk-title text-3xl">Scout the web</h2>
        <p className="rk-muted text-sm mt-1 max-w-3xl">
          Looks the dish up and reads each page's own recipe data, in code, word for word. No model rewrites it. Pages
          that block readers or do not publish that data are skipped. Nothing is kept unless you keep it.
        </p>
        <div className="mt-3 flex flex-wrap gap-3 items-center">
          <button type="button" className="rk-btn" disabled={webBusy || query.trim().length < 2} onClick={() => searchWeb()}>
            {webBusy ? <Loader2 size={18} className="animate-spin" /> : <Globe size={18} />}
            {query.trim().length < 2 ? 'Type a dish above first' : `Scout “${query.trim().slice(0, 30)}”`}
          </button>
          <form
            className="flex flex-1 min-w-[16rem] gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              void importUrl(url).then(() => setUrl(''));
            }}
          >
            <input
              className="rk-input"
              type="url"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="…or paste a recipe page address"
              aria-label="Recipe page address"
              maxLength={2000}
            />
            <button type="submit" className="rk-btn rk-btn-plain" disabled={webBusy || !url.trim()}>
              <Link2 size={18} /> Read it
            </button>
          </form>
        </div>
        {webSearched !== null && webResults.length === 0 && !webBusy && (
          <p className="rk-muted mt-3">No page gave up a readable recipe for “{webSearched}”.</p>
        )}
        {webResults.length > 0 && (
          <div className="grid gap-5 sm:grid-cols-2 xl:grid-cols-3 mt-4">
            {webResults.map((card, i) => <RecipeTile key={card.id} card={card} alt={i % 2 === 0} />)}
          </div>
        )}
      </section>
    </div>
  );
}
