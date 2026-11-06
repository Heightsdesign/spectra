export type InspectionAction = 'start' | 'pause' | 'resume';
export type InspectionEligibility = {
  eligible: boolean;
  reasons: { code: string; en: string; fr: string }[];
};
export type InspectionResult = {
  card: { reference: string };
  submission: { id: string; reference: string; customer_id: string };
  entry: { card_name: string; expansion: string; card_number: string; language: string } | null;
  inspection: { id: string; status: 'in_progress' | 'paused'; location: string; version: number } | null;
  eligibility: Record<InspectionAction | 'image', InspectionEligibility>;
  images: { id: string; side: string; version: number; sha256: string }[];
  custody: { id: string; actor_id: string; source: string; destination: string; reason: string; created_at: string }[];
};
export type InspectionCommand = {
  action: InspectionAction; reason: string; version: number; request_key: string;
};

export class InspectionError extends Error {
  code: string;
  reasons: InspectionEligibility['reasons'];
  constructor(code: string, reasons: InspectionEligibility['reasons'] = []) {
    super(code);
    this.code = code;
    this.reasons = reasons;
  }
}

export async function inspectionRequest(path: string, payload?: object, request: typeof fetch = fetch): Promise<InspectionResult> {
  const headers: Record<string, string> = {};
  if (payload) {
    const csrf = await request('/api/auth/csrf', { cache: 'no-store' });
    if (!csrf.ok) throw new InspectionError('authentication_required');
    headers['X-CSRF-Token'] = (await csrf.json()).csrf_token;
    headers['X-Spectra-Client'] = '1';
    headers['Content-Type'] = 'application/json';
  }
  const response = await request('/internal/inspection' + path, {
    method: payload ? 'POST' : 'GET', cache: 'no-store', headers,
    body: payload ? JSON.stringify(payload) : undefined,
  });
  const result = await response.json();
  if (!response.ok) {
    throw new InspectionError(typeof result.detail === 'string' ? result.detail : 'operation_blocked', result.detail?.reasons ?? []);
  }
  return result;
}

export function inspectionError(error: unknown, language: 'FR' | 'EN') {
  const fr = language === 'FR';
  if (error instanceof InspectionError && error.reasons.length) {
    return error.reasons.map(r => fr ? r.fr : r.en).join(' ');
  }
  const code = error instanceof Error ? error.message : '';
  if (['authentication_required', 'staff_required'].includes(code)) return fr ? 'Accès du personnel indisponible. Reconnectez-vous.' : 'Staff access unavailable. Sign in again.';
  if (['invalid_card_reference', 'card_not_found'].includes(code)) return fr ? 'Référence PC invalide ou introuvable.' : 'Invalid or unknown PC reference.';
  if (code === 'stale_version') return fr ? 'La carte a changé. Identifiez-la à nouveau.' : 'The card has changed. Look it up again.';
  if (code === 'integrity_mismatch') return fr ? 'Le contrôle d’intégrité a échoué.' : 'The integrity check failed.';
  if (code === 'image_too_large') return fr ? 'L’image dépasse la taille maximale autorisée (25 Mio au maximum).' : 'The image exceeds the allowed size (at most 25 MiB).';
  return fr ? 'Opération impossible. Vérifiez la carte et actualisez avant de réessayer.' : 'Operation failed. Verify the card and refresh before retrying.';
}
