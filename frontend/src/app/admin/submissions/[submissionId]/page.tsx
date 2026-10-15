import { IntakeWorkspace } from '@/components/intake-workspace';
import { currentStaff } from '@/lib/server-staff';
export const metadata = { title: 'Submission intake / Réception de soumission' };
export default async function SubmissionIntakePage({ params }: { params: Promise<{ submissionId: string }> }) {
  const staff = await currentStaff();
  const { submissionId } = await params;
  return staff ? <IntakeWorkspace key={submissionId} initialLanguage={staff.language} role={staff.role} initialSubmissionId={submissionId} /> : null;
}
