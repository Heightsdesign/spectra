import { cookies } from "next/headers";
import { language } from "@/lib/i18n";
import type { AuthMode } from "@/lib/auth-validation";
import { AuthForm } from "./auth-ui";
import { Container } from "./ui";

export async function AuthPage({ mode }: { mode: AuthMode }) {
  const lang = language((await cookies()).get("spectra_language")?.value);
  return <section className="section"><Container><AuthForm mode={mode} initialLanguage={lang} /></Container></section>;
}
