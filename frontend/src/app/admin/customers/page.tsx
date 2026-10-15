import { CustomerDirectory } from '@/components/customer-operations';
import { currentStaff } from '@/lib/server-staff';
export const metadata = { title: 'Customer directory / Répertoire clients' };
export default async function CustomersPage() {
  const staff = await currentStaff();
  return staff ? <CustomerDirectory initialLanguage={staff.language} /> : null;
}
