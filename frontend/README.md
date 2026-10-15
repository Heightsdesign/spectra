# SPECTRA public frontend — W1

Next.js App Router application using strict TypeScript and Tailwind CSS v4. Public pages remain informational. W2 adds bilingual customer accounts through the existing FastAPI backend; see [Authentication and account management](../AUTHENTICATION.md) for setup and security details. Submissions, payments and grading integration are not included.

## Run locally

Use Node.js 22 LTS or newer and npm. From the repository root:

```powershell
cd frontend
npm install
npm run dev
```

Open <http://127.0.0.1:3000>. Public informational pages run without the backend. W2 authentication/account routes require FastAPI, PostgreSQL and migration `0002`; follow the root authentication guide. Both development and production scripts bind to loopback.

```powershell
npm run lint
npm run typecheck
npm run build
npm start
```

`typecheck` can run before `build`; the build also generates Next.js route types. `build` uses Next.js's webpack option to keep the local production build explicit. No remote font downloads, image hosts or environment variables are required. External access is needed to install packages.

### Validation status in the implementation environment

Dependencies and a package lockfile are now present. W1.1 validation runs lint with zero warnings, strict TypeScript checking and a production build; see `BRAND_REFINEMENT.md` for scope and asset verification. Use `npm ci` to reproduce the locked installation. Browser rendering and assistive-technology checks still need a manual pass.

## Routes

| Route | Purpose |
| --- | --- |
| `/` | Editorial homepage, philosophy, condition categories, process, transparency |
| `/services` | Planned service; clearly pending pricing and operational details |
| `/standards` | Developing philosophy and methodology; no finalized scale |
| `/how-it-works` | Planned submission process; submissions coming soon |
| `/verify` | Disabled certificate lookup preview; no records or requests |
| `/contact` | Disabled inquiry preview; no messages sent or stored |

Also includes a custom not-found view and `/robots.txt`. Submit Cards links to `/how-it-works`, not a checkout.

## Structure

```text
src/
  app/                App Router layouts, route pages, metadata, global styles
  components/
    header.tsx        Wordmark, active navigation, mobile menu
    footer.tsx        Shared footer navigation and launch status
    ui.tsx            Containers, buttons/links, headings, cards, fields, notices
  lib/content.ts      Shared category and planned-process copy
```

Public contact and certificate forms remain disabled previews. New auth/account components provide functional FR/EN forms backed by FastAPI, with server-side protected account routes. There are no analytics or external tracking scripts. See the W2 guide for routes, tests and local email handling.

## Design system

- Neutral black, white and gray surfaces with a purple-led saturated accent system. Exact purple, yellow, orange and green Tailwind theme tokens live in `globals.css`; see `ACCENT_SYSTEM.md` for usage and contrast checks. Existing component spacing and responsive geometry are retained.
- System Arial/Helvetica typography avoids external requests. Tight editorial heading spacing, a constrained 1,440px page container and generous section spacing establish the visual hierarchy.
- The hero uses overlapping, geometric card silhouettes, explicitly labeled illustrative rather than actual SPECTRA products. No third-party card artwork is used.
- `BrandLogo` displays the official supplied PNGs, unchanged. The full black lockup appears in the light header and the full white lockup in the dark footer. Standalone S variants provide compact branding and color-scheme-aware favicons.
- Layouts adapt at 1,000px, 700px and 360px; two-column content stacks on small screens. No fixed page widths are used.
- Semantic landmarks, a skip link, visible keyboard focus, active-page attributes, labeled controls and reduced-motion handling are included. The mobile navigation button exposes its expanded state and target.

## Metadata and launch decisions

Each page declares a title and description; the root supplies the title template, language and generic Open Graph information. As this is an incomplete public-site preview, metadata uses `noindex` and robots disallows crawling. These are discoverability controls, not authentication.

No canonical domain, sitemap URLs, social image, address, email, price, turnaround guarantee, certificate example or legal identity has been invented. Configure the real production domain, canonical URLs, sitemap, social assets and approved indexability when launch details are known. French localization, published business/legal/privacy details, approved service terms, any future SVG asset delivery and actual service specifications remain future work.

## Manual acceptance checklist

After dependency installation and successful automated checks:

1. Open all six routes plus an unknown route. Follow every header, footer and call-to-action link.
2. Test at 320px, 375px, 768px and desktop widths, including long text and 200% browser zoom; check for overflow.
3. Use only the keyboard to reach the skip link, mobile menu and all links. Confirm focus remains visible and current-page navigation is identified.
4. Confirm the contact/verification fields and buttons cannot submit, and the browser Network panel shows no application API requests.
5. Enable reduced motion. Check the monochrome contrast and readable text with accessibility tooling.

Browser rendering, keyboard interaction and assistive-technology behavior have not been exercised in this environment. The supplied responsive/accessibility implementation still needs this manual acceptance pass.

## W5.1 admin browser regression

Run `npm run build`, then `npm run test:admin-browser` from `frontend`. The script uses the installed Chrome executable (Windows default, or set `CHROME_PATH`) and a separate profile. Ports 18091–18093 must be free. It starts a production Next server with synthetic staff responses and intercepts browser intake/CSRF requests with a 36-card fixture; no operational account or database is used.

Checks cover `/admin` and submission detail at 1440 × 1000 and 390 × 844, compiled control styling, page overflow, semantic labels, FR/EN switching, compact inventory, footer hit testing and mouse/keyboard navigation, finalization confirmation, CSRF headers, stable creation retry keys, frozen forms, and operator restrictions. Screenshots are saved under `.visual-review/admin/`. This is frontend verification; backend enforcement remains covered by the backend suite. Screen-reader and real operator workflow acceptance remain manual checks.

W5.1b extends the same regression with the protected customer directory, pagination/search, customer contact and shipment addresses, submission history and snapshots, direct intake/customer links, card lookup, empty/error/retry states, private route headers and anonymous server-side redirect. See [CUSTOMER_OPERATIONS.md](../CUSTOMER_OPERATIONS.md) for architecture, routes, data handling and validation results. No migration is required.

W5.1c adds submission-scoped individual/batch label previews, downloads and reprints, including frozen cards, plus opaque v1 QR scanner input. The browser regression uses `backend/label_samples/sample-50x30.pdf` as a synthetic PDF fixture. See [PHYSICAL_LABELS.md](../PHYSICAL_LABELS.md) for payloads, profiles, staff endpoints, Windows PDF printing, calibration and physical QA limitations. No migration is required.
