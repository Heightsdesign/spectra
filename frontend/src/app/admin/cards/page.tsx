import { PhysicalCardLookup } from '@/components/customer-operations';
import { currentStaff } from '@/lib/server-staff';
export const metadata = { title: 'Physical-card traceability / Traçabilité des cartes' };
export default async function CardsPage() {
  const staff = await currentStaff();
  return staff ? <PhysicalCardLookup initialLanguage={staff.language} /> : null;
}
