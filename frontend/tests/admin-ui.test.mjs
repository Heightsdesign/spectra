import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { componentModule } from './tsx-render.mjs';

const { IntakeWorkspace } = await import(await componentModule('../src/components/intake-workspace.tsx'));
const { Footer } = await import(await componentModule('../src/components/footer.tsx'));
const { SectionHeading } = await import(await componentModule('../src/components/ui.tsx'));

test('admin initial render uses the shared container and one semantic page landmark', () => {
  for (const [lang, title] of [['FR', 'Réception physique'], ['EN', 'Physical intake']]) {
    const html = renderToStaticMarkup(createElement(IntakeWorkspace, { initialLanguage: lang, role: 'admin' }));
    assert.match(html, /class="container-shell intake-workspace"/);
    assert.match(html, new RegExp(`lang="${lang.toLowerCase()}"`));
    assert.ok(html.includes(title));
    assert.doesNotMatch(html, /<main/); // RootLayout owns the main landmark / skip target.
    assert.match(html, /<label[^>]*>[^<]+<input/);
    assert.match(html, /<label[^>]*>[^<]+<select/);
    assert.match(html, /role="region"[^>]+tabindex="0"/);
    assert.match(html, /<caption>/);
    assert.match(html, /scope="col"/);
    assert.match(html, /role="status" aria-live="polite"/);
  }
});

test('footer navigation points to real public pages and exposes keyboard links', async () => {
  const html = renderToStaticMarkup(createElement(Footer));
  for (const [href, label] of [['/services', 'Services'], ['/standards', 'Standards'], ['/how-it-works', 'The process'], ['/verify', 'Certificate verification'], ['/contact', 'Contact']]) {
    assert.ok(html.includes(`href="${href}"`));
    assert.ok(html.includes(label));
    await readFile(new URL(`../src/app${href}/page.tsx`, import.meta.url));
  }
  assert.doesNotMatch(html, /tabindex="-1"|aria-disabled|href="#"/);
});

test('informational section headings remain headings', () => {
  const html = renderToStaticMarkup(createElement(SectionHeading, { index: '03 / The process', title: 'From your collection. And back.' }));
  assert.match(html, /<h2>From your collection\. And back\.<\/h2>/);
  assert.doesNotMatch(html, /<a /);
});
