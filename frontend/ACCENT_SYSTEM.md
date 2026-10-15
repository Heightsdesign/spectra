# W1.2 — Vibrant accent system

This is a color refinement of the approved W1.1 layout. Page structures, dimensions, spacing, typography, card geometry, responsive breakpoints and official logo pixels remain unchanged. White/light-gray page surfaces and black navigation remain the foundation; existing dark sections remain dark. There are no new features or dependencies.

## Exact tokens

Defined in the existing Tailwind `@theme` in `src/app/globals.css`, available both as CSS variables and Tailwind color utilities:

| Token | Color | Role |
| --- | --- | --- |
| `--color-accent-purple` | `#8B2CFF` | Dominant: hero phrase, front card, primary hero CTA, section labels, link/active-nav underlines, process numerals |
| `--color-accent-yellow` | `#FFE500` | Supporting: rear hero card, selected CTA arrows, category identifier, footer hover underline |
| `--color-accent-orange` | `#FF5A1F` | Supporting: middle hero card, category identifier |
| `--color-accent-green` | `#39F500` | Supporting: hero geometric stripe, category identifier, light CTA hover on dark sections |

No pastel or translucent accent variants are used. Inner-page introduction markers, notices and shared navigation use purple rather than repeating all four colors. Category numbers and titles remain present, so color does not carry meaning alone. Important statuses retain their existing text and neutral styling. Disabled controls remain neutral.

## Text contrast

WCAG relative-luminance calculations for the combinations introduced:

| Foreground / background | Ratio |
| --- | --- |
| Purple / `#FAFAFA` | 5.16:1 |
| Purple / `#F0F0F0` | 4.72:1 |
| White / purple | 5.38:1 |
| `#FAFAFA` / purple | 5.16:1 |
| Black (`#141414`) / yellow | 14.44:1 |
| Black (`#141414`) / orange | 5.91:1 |
| Black (`#141414`) / green | 12.49:1 |

These exceed 4.5:1 for ordinary text. Yellow/green/orange identifiers use black text; purple identifiers and hero-card text use white. Purple is not used for small text on existing dark sections. Keyboard-focus outlines, semantic labels, mobile menu behavior and reduced-motion handling remain unchanged. Geometric details and arrows supplement text labels rather than replacing them.

## Verification and remaining review

Run sequentially from `frontend`: `npm run lint`, `npm run build`, `npm run typecheck`. Building before the standalone type check avoids races while Next.js regenerates `.next/types`.

Desktop/mobile browser review was attempted using installed headless Chrome, but its graphics subprocesses failed under environment restrictions. No screenshots or successful browser-size review are claimed. Source review confirms no layout, sizing or breakpoint changes; inspect all six public routes at 375px and desktop width in a working browser before accepting the visual result. Include the mobile menu, hero clipping, dark-section CTA hover and category identifiers. Build and text-contrast checks do not replace visual or assistive-technology testing.

Changed files: `src/app/globals.css`, the illustration's accessible description in `src/components/collector-composition.tsx`, `README.md` and this document. `.gitignore` and `eslint.config.mjs` exclude the temporary `.visual-review` Chrome profile created during attempted QA; cleanup was blocked by automatic approval review. PNG assets, the logo component, business copy, backend and inactive forms are unchanged.
