/**
 * Resolves the hero theme for consumers that cannot read CSS custom
 * properties directly — currently `ShapeWaves`, which paints to a
 * <canvas> 2D context via `fillStyle` and therefore needs a concrete
 * color string rather than `var(--hero-wave)`.
 *
 * The authored values live in the `:root` block at the top of
 * `src/index.css`; this module only mirrors them at runtime so there
 * is still exactly one place to edit the hero palette.
 *
 * Values are cached after first read — the hero theme is static for the
 * lifetime of the page, and `getComputedStyle` forces style recalc.
 */

let cache: HeroWaveColors | null = null;

export interface HeroWaveColors {
  color: string;
  hoverColor: string;
}

const DEFAULTS: HeroWaveColors = {
  color: "#0d3ef1",
  hoverColor: "#0a144a",
};

/**
 * Reads `--hero-wave` / `--hero-wave-hover` off the document root.
 * Falls back to the hardcoded defaults if the DOM is unavailable
 * (e.g. a non-browser test environment) or the property is unset.
 */
export function getHeroWaveColors(): HeroWaveColors {
  if (cache) return cache;

  if (typeof window === "undefined" || typeof document === "undefined") {
    cache = DEFAULTS;
    return cache;
  }

  const styles = window.getComputedStyle(document.documentElement);
  const read = (name: string, fallback: string): string => {
    const value = styles.getPropertyValue(name).trim();
    return value.length > 0 ? value : fallback;
  };

  cache = {
    color: read("--hero-wave", DEFAULTS.color),
    hoverColor: read("--hero-wave-hover", DEFAULTS.hoverColor),
  };
  return cache;
}
