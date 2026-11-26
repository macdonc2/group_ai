import { ArrowLeft, Check, ExternalLink, Loader2, Plus, RefreshCw, Trash2 } from 'lucide-react';
import { cn } from '../../lib/utils';
import { useRecipeStore } from '../../stores/recipeStore';
import type { IngredientLine, PhotoCredit, RecipeUnit, UnitSystem } from '../../types/recipes';
import { useApiImage } from './images';
import { DishShot, SourceBadge } from './parts';

const UNIT_NAMES: Record<RecipeUnit, string> = {
  tsp: 'teaspoons', tbsp: 'tablespoons', fl_oz: 'fluid ounces', cup: 'cups', pint: 'pints', quart: 'quarts',
  gallon: 'gallons', ml: 'millilitres', l: 'litres', oz: 'ounces', lb: 'pounds', g: 'grams', kg: 'kilograms',
};
const SYSTEMS: { value: UnitSystem; label: string }[] = [
  { value: 'original', label: 'As written' },
  { value: 'us', label: 'US' },
  { value: 'metric', label: 'Metric' },
];
const SCALES = [{ value: '1/2', label: '½×' }, { value: '1', label: '1×' }, { value: '2', label: '2×' }, { value: '3', label: '3×' }];
const WEIGHT: RecipeUnit[] = ['oz', 'lb', 'g', 'kg'];

function IngredientPhoto({ line, credit }: { line: IngredientLine; credit?: PhotoCredit }) {
  const address = useApiImage(line.photo && credit?.available ? `/recipes/ingredient-photos/${line.photo}` : null);
  const letter = (line.name.match(/[A-Za-z]/)?.[0] ?? '?').toUpperCase();
  return (
    <span className="rk-photo" aria-hidden="true">
      {address ? <img src={address} alt="" loading="lazy" /> : letter}
    </span>
  );
}

function IngredientRow({ line, credit }: { line: IngredientLine; credit?: PhotoCredit }) {
  const setLineUnit = useRecipeStore((s) => s.setLineUnit);
  const chosen = useRecipeStore((s) => s.units[line.index]);
  const isWeight = line.unit ? WEIGHT.includes(line.unit) : false;
  return (
    <li className="rk-row">
      <IngredientPhoto line={line} credit={credit} />
      <div className="flex-1 min-w-0">
        <p className="text-[15px] leading-snug font-medium">{line.text}</p>
        <p className="flex flex-wrap gap-1.5 mt-0.5 empty:hidden">
          {line.converted && <span className="rk-sub text-xs">as written: {line.raw}</span>}
          {line.approximate && (
            <span className="rk-flag rk-flag-approx" title="Volume to weight uses a typical density for this ingredient, so it is close, not exact.">
              ≈ by typical density
            </span>
          )}
          {line.not_scaled && (
            <span className="rk-flag rk-flag-warn" title="This line holds more than one amount, so it was left as written. Adjust it by hand.">
              not scaled: adjust by hand
            </span>
          )}
        </p>
      </div>
      {line.unit && line.can_convert_to.length > 0 && (
        <select
          className="rk-unit"
          aria-label={`Unit for ${line.name}`}
          value={line.unit}
          onChange={(e) => setLineUnit(line.index, e.target.value === '' ? null : (e.target.value as RecipeUnit))}
        >
          <option value={line.unit}>{UNIT_NAMES[line.unit]}</option>
          {chosen && <option value="">(back to default)</option>}
          {line.can_convert_to.map((unit) => (
            <option key={unit} value={unit}>
              {UNIT_NAMES[unit]}{WEIGHT.includes(unit) !== isWeight ? ' ≈' : ''}
            </option>
          ))}
        </select>
      )}
    </li>
  );
}

const PICTURE_NOTES: Record<string, string> = {
  none: 'Keep this recipe and its picture is made for you.',
  pending: 'The picture is being made. It takes about half a minute.',
  no_key: 'No OpenAI key is available, so no picture was made.',
  off: 'Dish pictures are switched off.',
};

/** One recipe, opened: the poster, the tale of the tape, ingredients with unit switching, the method. */
export function RecipeSheet() {
  const detail = useRecipeStore((s) => s.detail);
  const loading = useRecipeStore((s) => s.loadingDetail);
  const lines = useRecipeStore((s) => s.lines);
  const scale = useRecipeStore((s) => s.scale);
  const system = useRecipeStore((s) => s.system);
  const converting = useRecipeStore((s) => s.converting);
  const credits = useRecipeStore((s) => s.credits);
  const close = useRecipeStore((s) => s.close);
  const keep = useRecipeStore((s) => s.keep);
  const drop = useRecipeStore((s) => s.drop);
  const retryPicture = useRecipeStore((s) => s.retryPicture);
  const setScale = useRecipeStore((s) => s.setScale);
  const setSystem = useRecipeStore((s) => s.setSystem);

  if (loading || !detail) {
    return <div className="flex justify-center py-20"><Loader2 className="w-8 h-8 animate-spin" /></div>;
  }

  const { recipe } = detail;
  const tape = [
    ['Prep', detail.times.prep], ['Cook', detail.times.cook], ['Total', detail.times.total],
    ['Feeds', detail.servings], ['Division', detail.category === 'other' ? null : detail.category],
  ].filter((row): row is [string, string] => Boolean(row[1]));
  const shown = [...new Map(lines.flatMap((g) => g.items).map((i) => [i.photo, i.photo ? credits[i.photo] : undefined])).values()]
    .filter((c): c is PhotoCredit => Boolean(c?.available));
  const remove = () => {
    if (detail.source === 'cookbook' || window.confirm(`Take "${detail.title}" off your list? It is not in a cookbook, so it will be deleted.`)) {
      void drop(detail.id);
    }
  };
  const canRetry = ['failed', 'capped', 'no_key'].includes(detail.image_status) || (detail.saved && detail.image_status === 'none');

  return (
    <article className="space-y-5">
      <button type="button" className="rk-btn rk-btn-sm rk-btn-plain" onClick={close}>
        <ArrowLeft size={14} /> Back to the card
      </button>

      <header className="grid gap-5 lg:grid-cols-[minmax(0,22rem)_1fr] items-start">
        <div>
          <DishShot recipe={detail} className="aspect-square w-full rounded-xl border-[3px] border-black shadow-[6px_6px_0_var(--rk-a)]" wordClass="text-4xl" />
          {detail.image_status !== 'done' && (
            <p className="rk-muted text-xs mt-2 flex flex-wrap items-center gap-2">
              {detail.image_note ?? PICTURE_NOTES[detail.image_status] ?? ''}
              {canRetry && (
                <button type="button" className="underline inline-flex items-center gap-1" onClick={() => retryPicture(detail.id)}>
                  <RefreshCw size={12} /> try the picture again
                </button>
              )}
            </p>
          )}
        </div>
        <div className="space-y-3 min-w-0">
          <p className="rk-kicker">Tonight&apos;s main event</p>
          <h1 className="rk-title text-5xl sm:text-6xl break-words">{detail.title}</h1>
          <div className="flex flex-wrap items-center gap-2">
            <SourceBadge source={detail.source} />
            <span className="rk-muted text-sm">{detail.source_label}</span>
          </div>
          {recipe.attribution && <p className="rk-muted text-sm">Credit: {recipe.attribution}</p>}
          {recipe.source_url && (
            <a href={recipe.source_url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-sm underline text-[var(--rk-gold)]">
              <ExternalLink size={13} /> Open the original page
            </a>
          )}
          {tape.length > 0 && (
            <dl className="rk-tape" aria-label="Tale of the tape">
              {tape.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}
            </dl>
          )}
          <div className="flex flex-wrap gap-3 pt-1">
            {detail.saved ? (
              <>
                <span className="rk-btn rk-btn-gold cursor-default"><Check size={18} /> On my list</span>
                <button type="button" className="rk-btn rk-btn-plain" onClick={remove}>
                  <Trash2 size={16} /> {detail.source === 'cookbook' ? 'Take off my list' : 'Delete'}
                </button>
              </>
            ) : (
              <button type="button" className="rk-btn rk-btn-big" onClick={() => keep(detail.id)}>
                <Plus size={22} /> Keep it
              </button>
            )}
          </div>
          {detail.source === 'model' && (
            <p className="rk-note rk-note-warn">
              <strong>Written by a language model. Nobody has cooked this.</strong> Read it through before you start, and
              trust a thermometer over its times.
            </p>
          )}
          {!recipe.complete && (
            <div className="rk-note rk-note-warn">
              <strong>This cookbook entry is incomplete.</strong>
              {recipe.gaps.length > 0 && <ul className="list-disc pl-5 mt-1">{recipe.gaps.map((g) => <li key={g}>{g}</li>)}</ul>}
            </div>
          )}
        </div>
      </header>

      <div className="grid gap-5 xl:grid-cols-[minmax(0,5fr)_minmax(0,6fr)] items-start">
        <section className="rk-card p-4" aria-label="Ingredients">
          <h2 className="rk-display text-3xl">The tag team</h2>
          <p className="rk-sub text-xs mb-3">Ingredients. Amounts are scaled and converted by arithmetic, not by a model.</p>
          <div className="flex flex-wrap gap-3 mb-3 items-center">
            <div className="rk-seg" role="group" aria-label="Units">
              {SYSTEMS.map((s) => (
                <button key={s.value} type="button" aria-pressed={system === s.value} onClick={() => setSystem(s.value)}>{s.label}</button>
              ))}
            </div>
            <div className="rk-seg" role="group" aria-label="Scale the recipe">
              {SCALES.map((s) => (
                <button key={s.value} type="button" aria-pressed={scale === s.value} onClick={() => setScale(s.value)}>{s.label}</button>
              ))}
            </div>
            {converting && <Loader2 size={16} className="animate-spin" />}
          </div>
          {lines.length === 0 && <p className="text-sm">No ingredients were recorded for this entry.</p>}
          {lines.map((group, g) => (
            <div key={`${group.name ?? ''}-${g}`} className={cn(g > 0 && 'mt-4')}>
              {group.name && <h3 className="rk-display text-xl mb-1">{group.name}</h3>}
              <ul>
                {group.items.map((line) => (
                  <IngredientRow key={line.index} line={line} credit={line.photo ? credits[line.photo] : undefined} />
                ))}
              </ul>
            </div>
          ))}
          {scale !== '1' && detail.servings && (
            <p className="rk-sub text-xs mt-3">The recipe says “{detail.servings}” at 1×. Cooking times do not scale with the amounts.</p>
          )}
          {shown.length > 0 && (
            <details className="mt-3 text-xs rk-sub">
              <summary className="cursor-pointer font-semibold">Ingredient photo credits (Wikimedia Commons)</summary>
              <ul className="mt-1 space-y-0.5">
                {shown.map((c) => (
                  <li key={c.key}>
                    <span className="font-semibold">{c.key}</span>:{' '}
                    {c.source_url ? <a href={c.source_url} target="_blank" rel="noopener noreferrer">{c.title ?? 'photo'}</a> : c.title}
                    {c.author ? ` by ${c.author}` : ''}
                    {c.license_name && (
                      <>, {c.license_url ? <a href={c.license_url} target="_blank" rel="noopener noreferrer">{c.license_name}</a> : c.license_name}</>
                    )}
                  </li>
                ))}
              </ul>
            </details>
          )}
        </section>

        <div className="space-y-5">
          <section className="rk-card rk-card-alt p-4" aria-label="Method">
            <h2 className="rk-display text-3xl mb-1">The game plan</h2>
            {recipe.steps.length === 0 && <p className="text-sm">No method was recorded for this entry.</p>}
            <ol>
              {recipe.steps.map((step, i) => (
                <li key={i} className="rk-round">
                  <span className="rk-round-no">Round<b>{i + 1}</b></span>
                  <p className="text-[15px] leading-relaxed pt-1">{step}</p>
                </li>
              ))}
            </ol>
          </section>

          {recipe.variants.map((variant) => (
            <section key={variant.name} className="rk-card p-4" aria-label={variant.name}>
              <h2 className="rk-display text-2xl">Rematch: {variant.name}</h2>
              {variant.untested && <p className="rk-flag rk-flag-warn inline-block mb-1">untested conversion</p>}
              <ol className="list-decimal pl-5 space-y-1 text-[15px]">{variant.steps.map((s, i) => <li key={i}>{s}</li>)}</ol>
            </section>
          ))}

          {(recipe.notes.length > 0 || recipe.substitutions.length > 0 || recipe.pairings.length > 0 || recipe.related.length > 0) && (
            <section className="rk-card p-4 space-y-3" aria-label="Notes">
              <h2 className="rk-display text-2xl">From the corner</h2>
              {recipe.notes.length > 0 && <ul className="list-disc pl-5 space-y-1 text-sm">{recipe.notes.map((n, i) => <li key={i}>{n}</li>)}</ul>}
              {recipe.substitutions.length > 0 && (
                <div>
                  <h3 className="font-bold text-sm">Swaps</h3>
                  <ul className="list-disc pl-5 space-y-1 text-sm">{recipe.substitutions.map((n, i) => <li key={i}>{n}</li>)}</ul>
                </div>
              )}
              {recipe.pairings.length > 0 && <p className="text-sm"><span className="font-bold">Goes with:</span> {recipe.pairings.join(' · ')}</p>}
              {recipe.related.length > 0 && <p className="text-sm"><span className="font-bold">Uses:</span> {recipe.related.join(' · ')}</p>}
            </section>
          )}
        </div>
      </div>
    </article>
  );
}
