export type RecipeSource = 'cookbook' | 'model' | 'web';
export type UnitSystem = 'original' | 'us' | 'metric';
export type RecipeUnit =
  | 'tsp' | 'tbsp' | 'fl_oz' | 'cup' | 'pint' | 'quart' | 'gallon' | 'ml' | 'l' | 'oz' | 'lb' | 'g' | 'kg';
/** none | pending | done | failed | capped (daily limit) | no_key | off */
export type ImageStatus = 'none' | 'pending' | 'done' | 'failed' | 'capped' | 'no_key' | 'off';

export interface RecipeTimes {
  prep: string | null;
  cook: string | null;
  total: string | null;
}

/** A recipe in a list. */
export interface RecipeCard {
  id: string;
  title: string;
  source: RecipeSource;
  source_label: string;
  category: string;
  tags: string[];
  servings: string | null;
  times: RecipeTimes;
  complete: boolean;
  saved: boolean;
  image_status: ImageStatus;
  ingredient_count: number;
  /** Which of the person's ingredients it uses (search and pitch). */
  uses: string[];
  partial_match: boolean;
}

export interface PitchedCard extends RecipeCard {
  hype: string;
}

/** One ingredient line as the server computed it for the chosen scale and units. */
export interface IngredientLine {
  index: number;
  text: string;
  raw: string;
  amount: string | null;
  unit: RecipeUnit | null;
  unit_label: string | null;
  name: string;
  note: string | null;
  converted: boolean;
  approximate: boolean;
  not_scaled: boolean;
  can_convert_to: RecipeUnit[];
  photo: string | null;
}

export interface IngredientGroup {
  name: string | null;
  items: IngredientLine[];
}

export interface RecipeBody {
  title: string;
  source: RecipeSource;
  source_label: string;
  source_url: string | null;
  attribution: string | null;
  steps: string[];
  variants: { name: string; untested: boolean; steps: string[] }[];
  substitutions: string[];
  notes: string[];
  pairings: string[];
  related: string[];
  complete: boolean;
  gaps: string[];
}

export interface RecipeDetail extends RecipeCard {
  recipe: RecipeBody;
  ingredients: IngredientGroup[];
  image_note: string | null;
}

export interface RecipesStatus {
  cookbook_recipes: number;
  saved: number;
  categories: string[];
  pictures_per_day: number;
  pictures_today: number;
  pictures_available: boolean;
  ingredient_photos: boolean;
}

export interface ImportResult {
  added: number;
  updated: number;
  skipped: { id: string; reason: string }[];
  total: number;
}

export interface PhotoCredit {
  key: string;
  available: boolean;
  title: string | null;
  author: string | null;
  license_name: string | null;
  license_url: string | null;
  source_url: string | null;
}

export interface PitchRequest {
  craving: string;
  have: string[];
  avoid: string[];
  already_pitched: string[];
  count: number;
  allow_new: boolean;
  allow_web: boolean;
  persona?: string;
}

export interface RecipeStreamEvent {
  event_type: 'tool_result' | 'pitch' | 'error' | string;
  message: string;
  data?: {
    tool_name?: string;
    promo?: string;
    cards?: PitchedCard[];
    tools_used?: string[];
  } | null;
}
