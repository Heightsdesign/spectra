"use client";
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { customerOperationsCopy, type Language } from '@/lib/customer-operations';
import { useAdminLanguage } from './admin-language';

export function AdminNavigation({ language }: { language: Language }) {
  const path = usePathname();
  const [currentLanguage] = useAdminLanguage(language);
  const t = customerOperationsCopy[currentLanguage];
  return <nav className="container-shell admin-navigation" aria-label={currentLanguage === 'FR' ? 'Navigation interne' : 'Internal navigation'}>
    {([['/admin', t.intake], ['/admin/customers', t.clients], ['/admin/cards', t.lookup]] as const).map(([href, text]) =>
      <Link key={href} href={href} aria-current={(href === '/admin' ? path === href || path.startsWith('/admin/submissions/') : path.startsWith(href)) ? 'page' : undefined}>{text}</Link>)}
  </nav>;
}
