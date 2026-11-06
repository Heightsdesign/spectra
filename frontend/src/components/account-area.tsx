'use client';
import { AddressBook } from './checkout-panel';
import { useState } from 'react';
import Link from 'next/link';
import { messages } from '@/lib/i18n';
import type { Customer } from '@/lib/customer';
import { Submissions } from './submissions';
import { CardLibrary } from './card-library';
import { AccountActions } from './auth-ui';
import { Container } from './ui';

export function AccountArea({ customer: c, settings = false }: { customer: Customer; settings?: boolean }) {
  const [lang, setLang] = useState(c.preferred_language);
  const [tab, setTab] = useState<'orders' | 'cards'>('orders');
  const t = messages[lang];
  return <section className="section selby-account" lang={lang.toLowerCase()}><Container><div className={settings ? 'auth-panel' : undefined}>
    <header className="selby-account-header"><div><p className="eyebrow">SELBY / {t.account}</p><h1>{settings ? t.settings : `${t.welcome}, ${c.first_name}.`}</h1><p>{c.email} · {t.verified}</p></div>{!settings && <Link href="/account/settings" className="text-link">{t.settings} ↗</Link>}</header>
    {!settings && <><nav className="selby-account-tabs" aria-label={lang === 'FR' ? 'Votre espace' : 'Your space'}><button aria-pressed={tab === 'orders'} onClick={() => setTab('orders')}>{lang === 'FR' ? 'Mes commandes' : 'My orders'}</button><button aria-pressed={tab === 'cards'} onClick={() => setTab('cards')}>{lang === 'FR' ? 'Mes cartes' : 'My cards'}</button></nav><div hidden={tab !== 'orders'}><Submissions lang={lang} /></div><div hidden={tab !== 'cards'}><CardLibrary lang={lang} /></div></>}
    {settings && <AddressBook lang={lang} />}
    <AccountActions customer={c} settings={settings} onLanguageChange={setLang} />
    {settings && <Link href="/account" className="text-link">{t.back}</Link>}
  </div></Container></section>;
}
