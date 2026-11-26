import { useRecipeStore } from '../../stores/recipeStore';
import { DishShot } from './parts';

interface SavedListProps {
  onSelect?: () => void;
}

const SOURCE_WORDS = { cookbook: 'cookbook', model: 'model-written', web: 'web' } as const;

/** Sidebar: the recipes the person kept. */
export function SavedList({ onSelect }: SavedListProps) {
  const saved = useRecipeStore((s) => s.saved);
  const openId = useRecipeStore((s) => s.openId);
  const open = useRecipeStore((s) => s.open);

  return (
    <div className="flex flex-col h-full rk-side">
      <div className="p-4 border-b border-slate-200 dark:border-slate-700">
        <h2 className="font-semibold text-sm">The Locker Room</h2>
        <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
          {saved.length === 0 ? 'Recipes you keep show up here.' : `${saved.length} kept ${saved.length === 1 ? 'recipe' : 'recipes'}`}
        </p>
      </div>
      <ul className="flex-1 overflow-y-auto p-2 space-y-0.5">
        {saved.map((card) => (
          <li key={card.id}>
            <button
              type="button"
              className="rk-side-item"
              aria-current={openId === card.id}
              onClick={() => {
                void open(card.id);
                onSelect?.();
              }}
            >
              <DishShot recipe={card} className="rk-side-thumb" wordClass="text-[9px] leading-none" />
              <span className="min-w-0">
                <span className="block text-sm font-medium truncate">{card.title}</span>
                <span className="block text-xs text-slate-500 dark:text-slate-400 truncate">
                  {SOURCE_WORDS[card.source] ?? card.source} · {card.category}
                </span>
              </span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
