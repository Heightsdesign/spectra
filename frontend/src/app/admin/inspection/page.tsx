import { currentStaff } from '@/lib/server-staff';
import { InspectionWorkstation } from '@/components/inspection-workstation';
export default async function Page() { const staff = await currentStaff(); return staff ? <InspectionWorkstation initialLanguage={staff.language} /> : null; }
