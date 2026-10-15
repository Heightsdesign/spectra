"use client";

import { useEffect, useState, type FormEvent } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { messages, language, type Language, type MessageKey } from "@/lib/i18n";
import { validateAuth, type AuthMode } from "@/lib/auth-validation";
import type { Customer } from "@/lib/customer";
import { FormField } from "./ui";

function rememberLanguage(value: Language) {
  document.cookie = `spectra_language=${value}; Path=/; Max-Age=31536000; SameSite=Lax${location.protocol === "https:" ? "; Secure" : ""}`;
}

async function authRequest(path: string, payload: object, protectedWrite = false, method = "POST") {
  const headers: Record<string, string> = { "Content-Type": "application/json", "X-Spectra-Client": "1" };
  if (protectedWrite) {
    const csrf = await fetch("/api/auth/csrf", { cache: "no-store" });
    if (!csrf.ok) throw new Error("authentication_required");
    headers["X-CSRF-Token"] = (await csrf.json()).csrf_token;
  }
  const response = await fetch(`/api/auth${path}`, { method, headers, body: JSON.stringify(payload), cache: "no-store" });
  const result = await response.json();
  if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : "invalid_input");
  return result;
}

function messageKey(error: unknown): MessageKey {
  const key = error instanceof Error ? error.message : "unavailable";
  return key in messages.EN ? key as MessageKey : "unavailable";
}

function LanguageSelector({ value, onChange }: { value: Language; onChange: (language: Language) => void }) {
  return <label className="auth-language">{messages[value].languageLabel}<select value={value} onChange={e => { const lang = language(e.target.value); rememberLanguage(lang); onChange(lang); }}><option value="FR">Français</option><option value="EN">English</option></select></label>;
}

export function AuthForm({ mode, initialLanguage }: { mode: AuthMode; initialLanguage: Language }) {
  const router = useRouter();
  const [lang, setLang] = useState(initialLanguage);
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<MessageKey | null>(null);
  const [error, setError] = useState(false);
  const [done, setDone] = useState(false);
  const t = messages[lang];
  useEffect(() => {
    // Read browser-only URL fragments after hydration; never send them to SSR.
    const timer = window.setTimeout(() => {
    if (mode === "login") {
      const value = new URLSearchParams(location.search).get("notice");
      if (value === "password_changed" || value === "password_reset") { setNotice(value); setError(false); }
    }
    if (mode !== "verify" && mode !== "reset") return;
    const fragment = new URLSearchParams(location.hash.slice(1));
    const value = fragment.get("token") ?? "";
    setToken(/^[A-Za-z0-9_-]{43}$/.test(value) ? value : "");
    if (fragment.has("lang")) { const preference = language(fragment.get("lang")); setLang(preference); rememberLanguage(preference); }
    if (location.hash) history.replaceState(null, "", location.pathname);
    }, 0);
    return () => window.clearTimeout(timer);
  }, [mode]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const values = Object.fromEntries(new FormData(event.currentTarget)) as Record<string, string>;
    const invalid = validateAuth(mode, values);
    if (invalid) { setError(true); setNotice(invalid); return; }
    if ((mode === "verify" || mode === "reset") && !token) { setError(true); setNotice("missingToken"); return; }
    setBusy(true); setNotice(null);
    try {
      const paths = { register: "/register", login: "/login", verify: "/verify-email", forgot: "/password/reset/request", reset: "/password/reset" };
      const payload = mode === "register" ? { email: values.email, password: values.password, first_name: values.first_name, last_name: values.last_name, preferred_language: lang } : mode === "login" ? { email: values.email, password: values.password } : mode === "forgot" ? { email: values.email } : mode === "verify" ? { token } : { token, password: values.password };
      const result = await authRequest(paths[mode], payload);
      if (mode === "login") { rememberLanguage(language(result.preferred_language)); router.replace("/account"); router.refresh(); return; }
      setError(false); setNotice(result.message as MessageKey); setDone(true); setToken("");
    } catch (e) { setError(true); setNotice(messageKey(e)); }
    finally { setBusy(false); }
  }

  async function resend(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setNotice(null);
    const email = new FormData(event.currentTarget).get("email");
    try { await authRequest("/verification/request", { email }); setError(false); setNotice("check_email"); }
    catch (e) { setError(true); setNotice(messageKey(e)); }
    finally { setBusy(false); }
  }

  return <div lang={lang.toLowerCase()} className="auth-panel"><LanguageSelector value={lang} onChange={setLang} /><h1>{t[mode]}</h1><p className="intro-copy">{t.intro}</p>
    {notice && <p className="auth-feedback" role={error ? "alert" : "status"}>{t[notice]}</p>}
    {!done && <form onSubmit={submit} aria-busy={busy}><fieldset disabled={busy}>
      {mode === "register" && <div className="form-pair"><FormField id="first_name" name="first_name" label={t.first_name} autoComplete="given-name" required maxLength={100} /><FormField id="last_name" name="last_name" label={t.last_name} autoComplete="family-name" required maxLength={100} /></div>}
      {["register", "login", "forgot"].includes(mode) && <FormField id="email" name="email" label={t.email} type="email" autoComplete="email" required maxLength={254} />}
      {["register", "login", "reset"].includes(mode) && <FormField id="password" name="password" label={t.password} type="password" autoComplete={mode === "login" ? "current-password" : "new-password"} required minLength={mode === "login" ? 1 : 12} maxLength={128} hint={mode === "login" ? undefined : t.passwordHint} />}
      {["register", "reset"].includes(mode) && <FormField id="confirm" name="confirm" label={t.confirm} type="password" autoComplete="new-password" required minLength={12} maxLength={128} />}
      {(mode === "verify" || mode === "reset") && !token && <p className="field-hint">{t.missingToken}</p>}
      <button className="button button-dark" type="submit" disabled={busy || ((mode === "verify" || mode === "reset") && !token)}>{busy ? t.busy : t[mode]}</button>
    </fieldset></form>}
    {mode === "verify" && <form onSubmit={resend} className="auth-resend"><h2>{t.resend}</h2><FormField id="resend_email" name="email" label={t.email} type="email" autoComplete="email" required maxLength={254} /><button className="button button-outline" disabled={busy}>{t.resend}</button></form>}
    <nav className="auth-links" aria-label={t.account}><Link href="/login">{t.login}</Link><Link href="/register">{t.register}</Link><Link href="/forgot-password">{t.forgot}</Link><Link href="/verify-email">{t.verify}</Link></nav>
  </div>;
}

export function AccountActions({ customer, settings = false, onLanguageChange }: { customer: Customer; settings?: boolean; onLanguageChange?: (value: Language) => void }) {
  const router = useRouter();
  const [lang, setLang] = useState(customer.preferred_language);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<MessageKey | null>(null);
  const t = messages[lang];
  async function run(path: string, values: object, method = "POST") {
    setBusy(true); setNotice(null);
    try {
      await authRequest(path, values, true, method);
      if (path !== "/profile") { rememberLanguage(lang); router.replace(path === "/password/change" ? "/login?notice=password_changed" : "/login"); router.refresh(); }
      else { rememberLanguage(lang); setNotice("saved"); }
    } catch (e) { setNotice(messageKey(e)); }
    finally { setBusy(false); }
  }
  return <div lang={lang.toLowerCase()}><LanguageSelector value={lang} onChange={value => { setLang(value); onLanguageChange?.(value); }} />{notice && <p role={notice === "saved" ? "status" : "alert"} className="auth-feedback">{t[notice]}</p>}
    {settings && <>
      <form onSubmit={event => { event.preventDefault(); const values = Object.fromEntries(new FormData(event.currentTarget)); void run("/profile", { ...values, preferred_language: lang }, "PATCH"); }}><fieldset disabled={busy}><legend>{t.settings}</legend><FormField id="profile_first_name" name="first_name" label={t.first_name} defaultValue={customer.first_name} autoComplete="given-name" required maxLength={100} /><FormField id="profile_last_name" name="last_name" label={t.last_name} defaultValue={customer.last_name} autoComplete="family-name" required maxLength={100} /><p className="field-hint">{customer.email} — {t.emailFixed}</p><button className="button button-dark" disabled={busy}>{t.save}</button></fieldset></form>
      <form className="auth-password" onSubmit={event => { event.preventDefault(); const values = Object.fromEntries(new FormData(event.currentTarget)) as Record<string, string>; if (values.new_password !== values.confirm) { setNotice("mismatch"); return; } void run("/password/change", { current_password: values.current_password, new_password: values.new_password }); }}><fieldset disabled={busy}><legend>{t.changePassword}</legend><FormField id="current_password" name="current_password" label={t.current_password} type="password" autoComplete="current-password" required maxLength={128} /><FormField id="new_password" name="new_password" label={t.new_password} type="password" autoComplete="new-password" required minLength={12} maxLength={128} hint={t.passwordHint} /><FormField id="new_confirm" name="confirm" label={t.confirm} type="password" autoComplete="new-password" required minLength={12} maxLength={128} /><button className="button button-dark" disabled={busy}>{t.changePassword}</button></fieldset></form>
    </>}
    <button className="button button-outline auth-logout" disabled={busy} onClick={() => void run("/logout", {})}>{t.logout}</button>
  </div>;
}
