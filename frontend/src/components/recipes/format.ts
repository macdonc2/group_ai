import type { RecipeCard } from '../../types/recipes';

/** "25 min · Serves 4" for a card, from whatever the recipe states. */
export function timeLine(card: Pick<RecipeCard, 'times' | 'servings'>): string {
  const { prep, cook, total } = card.times;
  const time = total ?? [prep && `${prep} prep`, cook && `${cook} cook`].filter(Boolean).join(' + ');
  return [time, card.servings].filter(Boolean).join(' · ');
}
