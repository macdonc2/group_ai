/**
 * Wrestler themes for the whole app: palette, headshot, copy, and the persona
 * key the backend uses to answer in that voice. Keys match
 * src/agent_system/adapters/outbound/llm/personas.py.
 */

export type WrestlerKey = 'macho_man' | 'hulk_hogan' | 'bret_hart' | 'mean_gene';
export type WrestlerChoice = WrestlerKey | 'none';

export interface Wrestler {
  key: WrestlerKey;
  name: string;
  shortName: string;
  tagline: string;        // under the app title / welcome screen
  welcome: string;        // empty-chat headline
  prompt: string;         // input placeholder
  thinking: string;       // "Thinking..." replacement
  icon: string;           // public path
  credit: string;
  font: string;           // display font for headings when this theme is on
  ttsTone: string;        // how the narration should be read (tone only)
  palette: {
    accent: string;       // primary fill (buttons, active tab)
    accent2: string;      // gradient partner
    glow: string;         // highlight text on dark
    ink: string;          // dark text on the accent band
    soft: string;         // subtle tinted background (rgba)
  };
}

export const WRESTLERS: Record<WrestlerKey, Wrestler> = {
  macho_man: {
    key: 'macho_man',
    name: '"Macho Man" Randy Savage',
    shortName: 'Macho Man',
    tagline: 'OHHH YEAAAH! The cream rises to the top.',
    welcome: 'DIG IT! What are we snappin’ into, brother?',
    prompt: 'Ask the Macho Man anything, brother…',
    thinking: 'Climbing the top rope…',
    icon: '/themes/macho_man.jpg',
    credit: 'Photo: Rob DiCaterino, CC BY 2.0, via Wikimedia Commons',
    font: "'Bangers', 'Anton', system-ui, sans-serif",
    ttsTone: 'gravelly, intense 1980s wrestling promo energy',
    palette: { accent: '#E11D2B', accent2: '#FF7A00', glow: '#FFD700', ink: '#3B0000', soft: 'rgba(255, 215, 0, 0.10)' },
  },
  hulk_hogan: {
    key: 'hulk_hogan',
    name: 'Hulk Hogan',
    shortName: 'Hulkster',
    tagline: 'Hulkamania is running wild!',
    welcome: 'Well let me tell you something, BROTHER!',
    prompt: 'Whatcha gonna do? Ask away, dude…',
    thinking: 'Hulking up…',
    icon: '/themes/hulk_hogan.jpg',
    credit: 'Photo: John McKeon, CC BY-SA 2.0, via Wikimedia Commons',
    font: "'Anton', system-ui, sans-serif",
    ttsTone: 'big, booming, all-American hype',
    palette: { accent: '#D7191C', accent2: '#F5B800', glow: '#FFD200', ink: '#4A0A00', soft: 'rgba(255, 210, 0, 0.10)' },
  },
  bret_hart: {
    key: 'bret_hart',
    name: 'Bret "The Hitman" Hart',
    shortName: 'The Hitman',
    tagline: 'The Excellence of Execution.',
    welcome: 'The best there is. What do you need?',
    prompt: 'Ask the Hitman. No shortcuts…',
    thinking: 'Executing, excellently…',
    icon: '/themes/bret_hart.jpg',
    credit: 'Photo: Tabercil, CC BY-SA 2.0, via Wikimedia Commons',
    font: "'Oswald', system-ui, sans-serif",
    ttsTone: 'calm, precise, quietly confident',
    palette: { accent: '#DB2777', accent2: '#7C3AED', glow: '#F9A8D4', ink: '#2E0A1F', soft: 'rgba(249, 168, 212, 0.10)' },
  },
  mean_gene: {
    key: 'mean_gene',
    name: '"Mean" Gene Okerlund',
    shortName: 'Mean Gene',
    tagline: 'Ladies and gentlemen, hold on just a minute!',
    welcome: 'Ladies and gentlemen, what’s on the marquee tonight?',
    prompt: 'Step up to the podium, folks…',
    thinking: 'Checking the card…',
    icon: '/themes/mean_gene.jpg',
    credit: 'Photo: Mark Hodgins, CC BY 2.0, via Wikimedia Commons',
    font: "'Playfair Display', Georgia, serif",
    ttsTone: 'polished broadcast announcer, brisk and urbane',
    palette: { accent: '#1D3F7A', accent2: '#C9A227', glow: '#E8C766', ink: '#0B2545', soft: 'rgba(232, 199, 102, 0.10)' },
  },
};

export const WRESTLER_KEYS: WrestlerKey[] = ['macho_man', 'hulk_hogan', 'bret_hart', 'mean_gene'];

export function getWrestler(choice: WrestlerChoice | null | undefined): Wrestler | null {
  return choice && choice !== 'none' ? WRESTLERS[choice] ?? null : null;
}

/** Push the palette into CSS variables and tag the root for CSS hooks. */
export function applyWrestler(choice: WrestlerChoice) {
  const root = document.documentElement;
  const w = getWrestler(choice);
  if (!w) {
    root.removeAttribute('data-wrestler');
    for (const v of ['accent', 'accent2', 'glow', 'ink', 'soft', 'icon', 'font']) root.style.removeProperty(`--wt-${v}`);
    return;
  }
  root.setAttribute('data-wrestler', w.key);
  root.style.setProperty('--wt-accent', w.palette.accent);
  root.style.setProperty('--wt-accent2', w.palette.accent2);
  root.style.setProperty('--wt-glow', w.palette.glow);
  root.style.setProperty('--wt-ink', w.palette.ink);
  root.style.setProperty('--wt-soft', w.palette.soft);
  root.style.setProperty('--wt-icon', `url("${w.icon}")`);
  root.style.setProperty('--wt-font', w.font);
}
