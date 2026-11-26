import { useEffect } from 'react';
import { AlertCircle, X } from 'lucide-react';
import { useRecipeStore, type RecipeMode } from '../../stores/recipeStore';
import { FindPanel } from './FindPanel';
import { PitchPanel } from './PitchPanel';
import { RecipeSheet } from './RecipeSheet';
import './recipes.css';

const MODES: { value: RecipeMode; label: string; sub: string }[] = [
  { value: 'find', label: 'Scout the roster', sub: 'Find a recipe' },
  { value: 'pitch', label: 'Call your shot', sub: 'Get dishes pitched' },
];

/** The Recipes tab: find a recipe, have dishes pitched, and open one to cook from. */
export function RecipesView() {
  const init = useRecipeStore((s) => s.init);
  const mode = useRecipeStore((s) => s.mode);
  const setMode = useRecipeStore((s) => s.setMode);
  const openId = useRecipeStore((s) => s.openId);
  const error = useRecipeStore((s) => s.error);
  const notice = useRecipeStore((s) => s.notice);
  const dismiss = useRecipeStore((s) => s.dismiss);

  useEffect(() => { void init(); }, [init]);

  return (
    <div className="rk-arena flex-1 min-h-0 overflow-y-auto">
      <div className="rk-ropes" aria-hidden="true" />
      <div className="max-w-6xl mx-auto px-4 sm:px-6 py-5 space-y-5">
        <header className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="rk-kicker">Live from the kitchen · one night only</p>
            <h1 className="rk-title text-5xl sm:text-6xl">Kitchen Stadium</h1>
          </div>
          <div className="rk-seg rk-seg-lg" role="group" aria-label="Recipes mode">
            {MODES.map((m) => (
              <button key={m.value} type="button" aria-pressed={mode === m.value && !openId} onClick={() => setMode(m.value)}>
                {m.label}
                <span className="block text-[10px] tracking-widest opacity-80 mt-0.5 font-sans font-bold">{m.sub}</span>
              </button>
            ))}
          </div>
        </header>

        {(error || notice) && (
          <div role={error ? 'alert' : 'status'} className={`rk-note ${error ? 'rk-note-error' : 'rk-note-info'} flex items-start gap-2`}>
            <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />
            <span className="flex-1">{error ?? notice}</span>
            <button type="button" onClick={dismiss} aria-label="Dismiss"><X className="w-4 h-4" /></button>
          </div>
        )}

        {openId ? <RecipeSheet /> : mode === 'find' ? <FindPanel /> : <PitchPanel />}
      </div>
    </div>
  );
}
