"use client";
import { createContext, useContext, useState, type ReactNode } from 'react';
import type { Language } from '@/lib/customer-operations';

const AdminLanguage = createContext<[Language, (value: Language) => void] | null>(null);
export function AdminLanguageProvider({ initialLanguage, children }: { initialLanguage: Language; children: ReactNode }) {
  const [language, setLanguage] = useState(initialLanguage);
  return <AdminLanguage.Provider value={[language, setLanguage]}>{children}</AdminLanguage.Provider>;
}
export function useAdminLanguage(initialLanguage: Language) {
  const shared = useContext(AdminLanguage);
  const fallback = useState<Language>(initialLanguage);
  return shared ?? fallback;
}
