import { IntakeWorkspace } from "@/components/intake-workspace";
import { currentStaff } from '@/lib/server-staff';

export const dynamic = 'force-dynamic';
export const metadata = { title: 'SPECTRA — Internal operations', robots: { index: false, follow: false } };
export default async function AdminPage() {
  const staff = await currentStaff();
  return staff ? <IntakeWorkspace initialLanguage={staff.language} role={staff.role} /> : null;
}
