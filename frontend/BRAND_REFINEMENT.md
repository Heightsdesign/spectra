# W1.1 — Brand integration and refinement

The W1 routes, section structure, system typography, monochrome palette and coming-soon behavior are retained. Hero copy uses the requested headline and supporting text. The old SP graphic is replaced with three overlapping card silhouettes, outlined artwork windows and understated geometric forms. No licensed collectible artwork, sample grades, certificate numbers or product photography are used. The illustration is explicitly labeled as not a SPECTRA product.

The supporting language now speaks to favourite pulls, childhood collections and chase cards. The services page identifies Pokémon, One Piece and other collectible card games as the initial focus, while retaining the pending eligibility notice. Shared card-shaped framing and a dark footer carry the refinement through the existing routes. Hover-capable devices receive a small card-fan movement and CTA arrow movement; reduced-motion settings suppress these interactions.

## Official assets

All four supplied PNGs were located under the root `imgs/` directory and copied unchanged into `public/brand/`. SHA-256 comparison confirms each copy is byte-identical. CSS does not filter, recolor, stretch or redraw the logos. The reusable `BrandLogo` component preserves the square source aspect ratio and uses a viewport around visible artwork to avoid excessive transparent margins. Only transparent canvas is excluded from that viewport.

| File | Source dimensions | Transparent pixels | Usage |
| --- | --- | --- | --- |
| `spectra_logo_full_black.png` | 5200 × 5200 | 95.06% | Full lockup on the light header |
| `spectra_logo_full_white.png` | 5200 × 5200 | 95.06% | Full lockup on the dark footer |
| `spectra_logo_black.png` | 1936 × 1936 | 71.32% | Standalone S for light-mode favicon and Apple icon |
| `spectra_logo_white.png` | 1936 × 1936 | 71.32% | Standalone S for dark-mode favicon and compact hero branding |

Inspection used both image viewing and RGBA pixel analysis. All files have alpha extrema 0–255 and partially transparent antialiased edges. Black variants have opaque black artwork and no opaque white background; white variants have opaque white artwork and no opaque black background. The full-lockup alpha bounding box is `(1273, 1278, 4310, 3824)` and the standalone bounding box is `(247, 127, 1737, 1851)`. Originals, including their transparent padding, remain intact. Icons reference the original standalone files; no substitute icon is generated.

## Files changed

- `src/components/brand-logo.tsx`, `collector-composition.tsx` — new official asset wrapper and hero composition.
- `src/components/header.tsx`, `footer.tsx` — official lockups, collector copy, dark footer.
- `src/app/page.tsx`, `globals.css`, `layout.tsx` — hero, shared visual refinement, metadata and favicon references.
- The five existing inner `page.tsx` modules — collector-oriented introductory language; services focus notice.
- `public/brand/*.png`, `.gitignore` — unchanged supplied assets and a narrow PNG tracking exception.
- `postcss.config.mjs` — named export object to satisfy the existing zero-warning lint command.
- `README.md`, this document — current setup, design and verification notes.

No backend, account, payment, submission or form-handler changes are included. Contact and lookup remain disabled previews, and business details remain pending. Production crawling remains disabled until launch configuration is approved.

## Verification

Validation completed from `frontend`:

- `npm run lint` — passed with zero warnings.
- `npm run build` — passed; all six public routes, the not-found page and robots output were generated.
- `npm run typecheck` — passed after the build finished generating route types. Do not run standalone TypeScript checking concurrently with a Next.js build because both use `.next/types`.
- Generated HTML inspection confirmed official full-lockup and favicon references across all six routes. SHA-256 verification confirmed all four PNG copies match the supplied originals.

The production build emitted a non-fatal notice about a package lockfile above the repository; that unrelated file was ignored by Next.js. Browser screenshots, device testing and assistive-technology interaction have not been performed in this environment. In particular, review logo readability at small sizes, mobile navigation, card-composition clipping, keyboard focus and reduced-motion behavior before release.
