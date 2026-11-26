import { Check, Plus } from 'lucide-react';
import { cn } from '../../lib/utils';
import { useRecipeStore } from '../../stores/recipeStore';
import type { RecipeCard } from '../../types/recipes';
import { timeLine } from './format';
import { DishShot, Loud, SourceBadge } from './parts';

/** One recipe on a card: picture, title, where it came from, and keep / open. */
export function RecipeTile({ card, hype, alt = false }: { card: RecipeCard; hype?: string; alt?: boolean }) {
  const open = useRecipeStore((s) => s.open);
  const keep = useRecipeStore((s) => s.keep);
  const drop = useRecipeStore((s) => s.drop);
  const facts = timeLine(card);

  const toggle = () => {
    if (!card.saved) return void keep(card.id);
    if (card.source === 'cookbook' || window.confirm(`Take "${card.title}" off your list? It is not in a cookbook, so it will be deleted.`)) {
      void drop(card.id);
    }
  };

  return (
    <article className={cn('rk-card rk-lift overflow-hidden flex flex-col', alt && 'rk-card-alt')}>
      <button type="button" className="rk-tile block w-full" onClick={() => open(card.id)} aria-label={`Open ${card.title}`}>
        <DishShot recipe={card} className="h-36 w-full" />
        <div className="p-3 pb-1">
          <SourceBadge source={card.source} />
          <h3 className="rk-display text-2xl mt-1.5">{card.title}</h3>
          <p className="rk-sub text-xs mt-1 truncate">{card.source_label}</p>
          {facts && <p className="text-[13px] font-semibold mt-1">{facts}</p>}
        </div>
      </button>
      <div className="px-3 pb-3 flex-1 flex flex-col gap-2">
        {hype && <p className="text-sm leading-snug italic">“<Loud text={hype} />”</p>}
        {card.uses.length > 0 && (
          <p className="text-xs"><span className="font-bold">Uses your:</span> {card.uses.join(', ')}</p>
        )}
        {card.partial_match && <p className="text-xs rk-sub">Matches some of your words, not all.</p>}
        {!card.complete && <p className="text-xs font-semibold text-amber-800">Incomplete cookbook entry</p>}
        <div className="mt-auto pt-1 flex gap-2">
          <button type="button" className="rk-btn rk-btn-sm rk-btn-plain flex-1" onClick={() => open(card.id)}>Open</button>
          <button
            type="button"
            className={cn('rk-btn rk-btn-sm flex-1', card.saved && 'rk-btn-gold')}
            onClick={toggle}
            aria-pressed={card.saved}
          >
            {card.saved ? <><Check size={14} /> On my list</> : <><Plus size={14} /> Keep it</>}
          </button>
        </div>
      </div>
    </article>
  );
}
