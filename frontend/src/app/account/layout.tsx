import { currentCustomer } from "@/lib/server-customer";
import { Container } from "@/components/ui";
import { cookies } from "next/headers";
import { language, messages } from "@/lib/i18n";

export const metadata = { title: "Mon compte / My account", robots: { index: false } };
export default async function AccountLayout({ children }: { children: React.ReactNode }) {
  const result = await currentCustomer();
  if (result.status !== "authenticated") {
    const lang = language((await cookies()).get("spectra_language")?.value);
    return <section className="section"><Container><p role="alert" lang={lang.toLowerCase()}>{messages[lang].serviceDown}</p></Container></section>;
  }
  return children;
}
