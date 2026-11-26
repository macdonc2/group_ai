import { useState, type KeyboardEvent } from 'react';
import { X } from 'lucide-react';
import { cn } from '../../lib/utils';
import type { ImageStatus, RecipeCard, RecipeSource } from '../../types/recipes';
import { useApiImage } from './images';

const BADGES: Record<RecipeSource, { label: string; className: string; title: string }> = {
  cookbook: { label: 'From the cookbook', className: 'rk-badge-cookbook', title: 'From your imported cookbooks, as printed.' },
  model: { label: 'Model-written · untested', className: 'rk-badge-model', title: 'Written by a language model. Nobody has cooked it.' },
  web: { label: 'From the web', className: 'rk-badge-web', title: "Read from the page's own recipe data, field for field." },
};

/** Where a recipe came from. Driven by the server's `source`, never by recipe text. */
export function SourceBadge({ source }: { source: RecipeSource }) {
  const badge = BADGES[source] ?? BADGES.model;
  return <span className={cn('rk-badge', badge.className)} title={badge.title}>{badge.label}</span>;
}

/** The dish picture, or a poster placeholder that says why there is none yet. */
export function DishShot({ recipe, className, wordClass = 'text-2xl' }: {
  recipe: Pick<RecipeCard, 'id' | 'title' | 'category' | 'image_status'>;
  className?: string;
  wordClass?: string;
}) {
  const status: ImageStatus = recipe.image_status;
  const address = useApiImage(status === 'done' ? `/recipes/${recipe.id}/image` : null);
  return (
    <div className={cn('rk-shot', className)}>
      {address ? (
        <img src={address} alt={`Picture of ${recipe.title}`} />
      ) : (
        <span className={cn('rk-shot-word', wordClass, status === 'pending' && 'rk-pulse')}>
          {status === 'pending' ? 'Picture on its way' : recipe.category === 'other' ? 'Main event' : recipe.category}
        </span>
      )}
    </div>
  );
}

/** Type a thing, press Enter or comma, get a chip. Used for "in my kitchen" and "avoid". */
export function ChipInput({ label, hint, values, onChange, placeholder, avoid = false, id }: {
  label: string;
  hint?: string;
  values: string[];
  onChange: (values: string[]) => void;
  placeholder: string;
  avoid?: boolean;
  id: string;
}) {
  const [draft, setDraft] = useState('');
  const add = (text: string) => {
    const fresh = text.split(',').map((t) => t.trim()).filter(Boolean)
      .filter((t) => !values.some((v) => v.toLowerCase() === t.toLowerCase()));
    if (fresh.length) onChange([...values, ...fresh].slice(0, 30));
    setDraft('');
  };
  // Read the box itself, not the `draft` in this closure: with fast typing a key can arrive
  // before the render that carries the previous one.
  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    const typed = e.currentTarget.value;
    if (e.key === 'Enter' && typed.trim()) {
      e.preventDefault();
      add(typed);
    } else if (e.key === 'Backspace' && !typed && values.length) {
      onChange(values.slice(0, -1));
    }
  };
  return (
    <div>
      <label htmlFor={id} className="rk-label block mb-1">{label}</label>
      {hint && <p className="rk-muted text-xs mb-1.5">{hint}</p>}
      <input
        id={id}
        className="rk-input"
        value={draft}
        onChange={(e) => (e.target.value.includes(',') ? add(e.target.value) : setDraft(e.target.value))}
        onKeyDown={onKey}
        onBlur={(e) => e.target.value.trim() && add(e.target.value)}
        placeholder={placeholder}
        maxLength={120}
      />
      {values.length > 0 && (
        <ul className="flex flex-wrap gap-1.5 mt-2" aria-label={label}>
          {values.map((value) => (
            <li key={value} className={cn('rk-chip', avoid && 'rk-chip-avoid')}>
              {value}
              <button type="button" aria-label={`Remove ${value}`} onClick={() => onChange(values.filter((v) => v !== value))}>
                <X size={13} />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** Promo text with **bold** shown as bold. Everything else is plain text: no links, no images, no HTML. */
export function Loud({ text }: { text: string }) {
  const parts = text.split(/\*\*([^*\n]+)\*\*/g);
  return <>{parts.map((part, i) => (i % 2 === 1 ? <strong key={i}>{part}</strong> : part))}</>;
}
