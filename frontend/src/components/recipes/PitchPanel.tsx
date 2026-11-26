import { Bell, Loader2, Minus, Plus } from 'lucide-react';
import { useRecipeStore } from '../../stores/recipeStore';
import { useThemeStore } from '../../stores/themeStore';
import { getWrestler } from '../../lib/wrestlers';
import { ChipInput, Loud } from './parts';
import { RecipeTile } from './RecipeTile';

/** Pitch: say what you fancy and what is in the kitchen; get a card of dishes with a promo. */
export function PitchPanel() {
  const form = useRecipeStore((s) => s.form);
  const setForm = useRecipeStore((s) => s.setForm);
  const pitch = useRecipeStore((s) => s.pitch);
  const pitching = useRecipeStore((s) => s.pitching);
  const activity = useRecipeStore((s) => s.activity);
  const promo = useRecipeStore((s) => s.promo);
  const cards = useRecipeStore((s) => s.cards);
  const status = useRecipeStore((s) => s.status);
  const wrestler = getWrestler(useThemeStore((s) => s.wrestler));
  const speaker = wrestler?.shortName ?? 'The Ring Chef';
  const nothingToSearch = status !== null && status.cookbook_recipes === 0 && !form.allowNew && !form.allowWeb;

  return (
    <div className="space-y-6">
      <form
        className="grid gap-4 lg:grid-cols-2"
        onSubmit={(e) => {
          e.preventDefault();
          void pitch();
        }}
      >
        <div className="lg:col-span-2">
          <label htmlFor="rk-craving" className="rk-label block mb-1">What are you hungry for?</label>
          <textarea
            id="rk-craving"
            className="rk-input resize-y"
            rows={2}
            maxLength={600}
            value={form.craving}
            onChange={(e) => setForm({ craving: e.target.value })}
            placeholder="Something spicy and fast for a weeknight… a big Sunday pot of something… leave it blank and be surprised."
          />
        </div>
        <ChipInput
          id="rk-have"
          label="In my kitchen"
          hint="What you want to use up."
          values={form.have}
          onChange={(have) => setForm({ have })}
          placeholder="chicken thighs, rice, limes…  (Enter to add)"
        />
        <ChipInput
          id="rk-avoid"
          label="Banned from the building"
          hint="Never pitched. Checked in code against each ingredient list by word, so it catches the obvious (peanuts in peanut butter), not what an ingredient contains. Read the recipe if it is an allergy."
          values={form.avoid}
          onChange={(avoid) => setForm({ avoid })}
          placeholder="cilantro, shellfish…  (Enter to add)"
          avoid
        />
        <div className="lg:col-span-2 flex flex-wrap items-center gap-x-6 gap-y-3">
          <div className="flex items-center gap-2">
            <span className="rk-label">Dishes on the card</span>
            <div className="rk-seg" role="group" aria-label="Dishes on the card">
              <button type="button" aria-label="Fewer" onClick={() => setForm({ count: Math.max(1, form.count - 1) })}><Minus size={14} /></button>
              <button type="button" aria-pressed="true" tabIndex={-1}>{form.count}</button>
              <button type="button" aria-label="More" onClick={() => setForm({ count: Math.min(5, form.count + 1) })}><Plus size={14} /></button>
            </div>
          </div>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" className="w-4 h-4" checked={form.allowNew} onChange={(e) => setForm({ allowNew: e.target.checked })} />
            Allow brand-new recipes <span className="rk-muted">(model-written, untested)</span>
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" className="w-4 h-4" checked={form.allowWeb} onChange={(e) => setForm({ allowWeb: e.target.checked })} />
            Scout the web too <span className="rk-muted">(slower)</span>
          </label>
        </div>
        <div className="lg:col-span-2 flex flex-wrap items-center gap-4">
          <button type="submit" className="rk-btn rk-btn-big" disabled={pitching || nothingToSearch}>
            {pitching ? <Loader2 size={24} className="animate-spin" /> : <Bell size={24} />} Ring the bell!
          </button>
          {pitching && (
            <p className="rk-display text-xl rk-pulse" role="status">{activity ?? wrestler?.thinking ?? 'The crowd is on its feet'}…</p>
          )}
          {nothingToSearch && (
            <p className="rk-muted text-sm">No cookbooks are loaded, so allow new recipes or the web.</p>
          )}
        </div>
      </form>

      {promo !== null && (
        <section aria-label="The promo" className="rk-promo p-4 sm:p-5">
          <div className="flex items-center gap-3 mb-2">
            {wrestler && (
              <img src={wrestler.icon} alt="" className="w-12 h-12 rounded-full object-cover border-2 border-black" />
            )}
            <div>
              <p className="rk-kicker">On the microphone</p>
              <p className="rk-title text-2xl">{speaker}</p>
            </div>
          </div>
          <p><Loud text={promo} /></p>
        </section>
      )}

      {cards.length > 0 && (
        <section aria-label="Tonight's card">
          <div className="flex flex-wrap items-end justify-between gap-3 mb-3">
            <h2 className="rk-title text-4xl">Tonight&apos;s card</h2>
            <button type="button" className="rk-btn rk-btn-sm rk-btn-plain" disabled={pitching} onClick={() => pitch(true)}>
              Pitch me {form.count} more
            </button>
          </div>
          <div className="grid gap-5 sm:grid-cols-2 xl:grid-cols-3">
            {cards.map((card, i) => <RecipeTile key={card.id} card={card} hype={card.hype} alt={i % 2 === 1} />)}
          </div>
        </section>
      )}
    </div>
  );
}
