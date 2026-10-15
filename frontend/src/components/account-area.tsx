"use client";
import { AddressBook } from "./checkout-panel";
import { useState } from "react";
import Link from "next/link";
import { messages } from "@/lib/i18n";
import type { Customer } from "@/lib/customer";
import { Submissions } from './submissions';
import { AccountActions } from "./auth-ui";
import { Container, InfoCard } from "./ui";

export function AccountArea({ customer: c, settings = false }: { customer: Customer; settings?: boolean }) {
  const [lang, setLang] = useState(c.preferred_language);
  const t = messages[lang];
  return <section className="section" lang={lang.toLowerCase()}><Container><div className={settings ? "auth-panel" : undefined}>
    {settings ? <h1>{t.settings}</h1> : <><p className="eyebrow">{t.account}</p><h1 className="account-title">{t.welcome}, {c.first_name}.</h1><p>{c.email} · {t.verified}</p><div className="info-grid account-grid"><InfoCard number="02" title={t.cards}>{t.comingSoon}. {t.empty}</InfoCard><article className="info-card"><h2>{t.settings}</h2><Link href="/account/settings" className="text-link">{t.settings} ↗</Link></article></div></>}
    {!settings && <Submissions lang={lang} />}
    {settings && <AddressBook lang={lang} />}
    <AccountActions customer={c} settings={settings} onLanguageChange={setLang} />
    {settings && <Link href="/account" className="text-link">{t.back}</Link>}
  </div></Container></section>;
}

