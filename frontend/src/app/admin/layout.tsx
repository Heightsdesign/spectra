import type { ReactNode } from 'react';
import { AdminNavigation } from '@/components/admin-navigation';
import { AdminLanguageProvider } from '@/components/admin-language';
import { currentStaff } from '@/lib/server-staff';

export const dynamic = 'force-dynamic';
export const metadata = { robots: { index: false, follow: false }, referrer: 'no-referrer' as const };
export default async function AdminLayout({ children }: { children: ReactNode }) {
  const staff = await currentStaff();
  if (!staff) return <section className="container-shell intake-workspace"><h1>Service indisponible / Service unavailable</h1></section>;
  return <AdminLanguageProvider initialLanguage={staff.language}><AdminNavigation language={staff.language} />{children}</AdminLanguageProvider>;
}
