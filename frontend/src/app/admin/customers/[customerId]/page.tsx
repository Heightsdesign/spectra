import { CustomerDetailWorkspace } from '@/components/customer-operations';
import { currentStaff } from '@/lib/server-staff';
export const metadata = { title: 'Customer account / Compte client' };
export default async function CustomerPage({ params }: { params: Promise<{ customerId: string }> }) {
  const staff = await currentStaff();
  const { customerId } = await params;
  return staff ? <CustomerDetailWorkspace key={customerId} customerId={customerId} initialLanguage={staff.language} /> : null;
}
