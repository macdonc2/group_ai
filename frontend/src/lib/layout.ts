import { useThemeStore } from '../stores/themeStore';

/**
 * Reading-column widths. The old fixed max-w-3xl wasted most of a wide
 * monitor; 'auto' now grows with the viewport and 'full' removes the cap.
 * Keep these as literal class strings so Tailwind's scanner picks them up.
 */
const WIDTHS = {
  chat: { auto: 'max-w-3xl xl:max-w-5xl 2xl:max-w-[88rem]', full: 'max-w-none' },
  report: { auto: 'max-w-3xl xl:max-w-4xl 2xl:max-w-6xl', full: 'max-w-none' },
  research: { auto: 'max-w-5xl 2xl:max-w-[96rem]', full: 'max-w-none' },
  composer: { auto: 'max-w-3xl xl:max-w-4xl', full: 'max-w-4xl' },
} as const;

export type WidthKind = keyof typeof WIDTHS;

export function useContentWidth(kind: WidthKind): string {
  const layout = useThemeStore((s) => s.layout);
  return WIDTHS[kind][layout];
}
