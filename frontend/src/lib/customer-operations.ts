export type Language = 'FR' | 'EN';
export const customerOperationsCopy = {
  EN: {
    clients: 'Customers', intake: 'Physical intake', lookup: 'Card lookup', title: 'Customer directory',
    search: 'Name, email or exact customer reference', searchHint: 'Use at least two characters for name or email searches.', find: 'Search',
    name: 'Name', email: 'Account email', status: 'Account status', date: 'Registered', reference: 'Customer reference',
    open: 'Open customer', previous: 'Previous', next: 'Next', loading: 'Loading…', empty: 'No records found.',
    error: 'Service unavailable. Please retry.', retry: 'Retry', notFound: 'Customer not found.',
    account: 'Customer account', verified: 'Email verified', active: 'Active', disabled: 'Disabled', yes: 'Yes', no: 'No',
    firstName: 'First name', lastName: 'Last name', addresses: 'Saved shipment addresses', recipient: 'Shipment recipient',
    phone: 'Shipment contact phone', instructions: 'Delivery instructions', noAccountPhone: 'No account phone number is stored. Shipment contact numbers are shown with their addresses.',
    history: 'Submission history', submissionStatus: 'Submission state', submitted: 'Submitted', created: 'Created', declared: 'Declared cards', intakeStatus: 'Intake state',
    intakeLink: 'Open intake', draft: 'Draft', submission: 'Submission', returnAddress: 'Submission return address',
    acceptedSnapshot: 'Historical return address recorded at terms acceptance', currentSelection: 'Current return address selection — not a historical snapshot',
    notRecorded: 'No historical return address was recorded.', noAddress: 'No return address selected.',
    association: 'This is the customer account associated with the submission. Association does not establish legal ownership of a card.',
    cardReference: 'Physical card reference or scanned QR', cardHint: 'Enter the full PC- reference or scan a SPECTRA v1 QR code, then press Enter.',
    trace: 'Physical-card traceability', card: 'Physical card', parcel: 'Intake parcel', entry: 'Declared entry', unidentified: 'No declared entry associated',
    customerLink: 'Open customer profile', lookupEmpty: 'Enter an exact reference to trace a physical card.',
    invalidCard: 'Enter a valid PC- reference (32 hexadecimal characters).', cardNotFound: 'Physical card not found.',
    inconsistent: 'The recorded relationships are inconsistent. Stop and request an operational review.',
    invalidSearch: 'Check the search text and pagination. Use at least two characters for names or emails.',
    auth: 'Your staff session is unavailable. Sign in again or contact an administrator.',
    language: 'Language', addressesTruncated: 'Only the first 100 saved addresses are shown.',
  },
  FR: {
    clients: 'Clients', intake: 'Réception physique', lookup: 'Recherche de carte', title: 'Répertoire clients',
    search: 'Nom, e-mail ou référence client exacte', searchHint: 'Utilisez au moins deux caractères pour un nom ou un e-mail.', find: 'Rechercher',
    name: 'Nom', email: 'E-mail du compte', status: 'État du compte', date: 'Inscription', reference: 'Référence client',
    open: 'Ouvrir le client', previous: 'Précédent', next: 'Suivant', loading: 'Chargement…', empty: 'Aucun enregistrement trouvé.',
    error: 'Service indisponible. Veuillez réessayer.', retry: 'Réessayer', notFound: 'Client introuvable.',
    account: 'Compte client', verified: 'E-mail vérifié', active: 'Actif', disabled: 'Désactivé', yes: 'Oui', no: 'Non',
    firstName: 'Prénom', lastName: 'Nom', addresses: 'Adresses de livraison enregistrées', recipient: 'Destinataire de l’envoi',
    phone: 'Téléphone de contact pour l’envoi', instructions: 'Instructions de livraison', noAccountPhone: 'Aucun téléphone n’est enregistré sur le compte. Les numéros de contact pour les envois figurent avec leurs adresses.',
    history: 'Historique des soumissions', submissionStatus: 'État de soumission', submitted: 'Soumise', created: 'Créée', declared: 'Cartes déclarées', intakeStatus: 'État de réception',
    intakeLink: 'Ouvrir la réception', draft: 'Brouillon', submission: 'Soumission', returnAddress: 'Adresse de retour de la soumission',
    acceptedSnapshot: 'Adresse de retour historique enregistrée lors de l’acceptation des conditions', currentSelection: 'Adresse de retour actuellement sélectionnée — pas un instantané historique',
    notRecorded: 'Aucune adresse de retour historique n’a été enregistrée.', noAddress: 'Aucune adresse de retour sélectionnée.',
    association: 'Il s’agit du compte client associé à la soumission. Cette association n’établit pas la propriété juridique d’une carte.',
    cardReference: 'Référence de carte physique ou QR scanné', cardHint: 'Saisissez la référence PC- complète ou scannez un QR SPECTRA v1, puis appuyez sur Entrée.',
    trace: 'Traçabilité des cartes physiques', card: 'Carte physique', parcel: 'Colis de réception', entry: 'Déclaration', unidentified: 'Aucune déclaration associée',
    customerLink: 'Ouvrir le profil client', lookupEmpty: 'Saisissez une référence exacte pour retrouver une carte physique.',
    invalidCard: 'Saisissez une référence PC- valide (32 caractères hexadécimaux).', cardNotFound: 'Carte physique introuvable.',
    inconsistent: 'Les relations enregistrées sont incohérentes. Arrêtez et demandez une vérification opérationnelle.',
    invalidSearch: 'Vérifiez la recherche et la pagination. Utilisez au moins deux caractères pour un nom ou un e-mail.',
    auth: 'Votre session du personnel est indisponible. Reconnectez-vous ou contactez un administrateur.',
    language: 'Langue', addressesTruncated: 'Seules les 100 premières adresses enregistrées sont affichées.',
  },
};
export type CustomerSummary = { id: string; first_name: string; last_name: string; email: string; status: 'active' | 'disabled'; created_at: string };
export type ShipmentAddress = { recipient: string; line1: string; line2: string; postal_code: string; city: string; country: string; phone: string; instructions: string };
export type CustomerDetail = CustomerSummary & { email_verified: boolean; saved_addresses: (ShipmentAddress & { id: string })[]; addresses_truncated: boolean };
export type CustomerSubmission = { id: string; reference: string; status: string; created_at: string; confirmed_at: string | null; declared_quantity: number; intake_status: string | null; return_address: ShipmentAddress | null; return_address_source: 'accepted_snapshot' | 'current_selection' | 'not_recorded' | null };
export type ResultPage<T> = { items: T[]; limit: number; offset: number; has_more: boolean };
export type CardTrace = { card: { id: string; reference: string; status: string }; declared_entry: { id: string; card_name: string; game: string; expansion: string; card_number: string; language: string } | null; parcel: { id: string; reference: string }; submission: { id: string; reference: string; status: string }; customer: Pick<CustomerSummary, 'id' | 'first_name' | 'last_name' | 'email'> };

export const customerProfileHref = (id: string) => `/admin/customers/${encodeURIComponent(id)}`;
export const intakeDetailHref = (id: string) => `/admin/submissions/${encodeURIComponent(id)}`;
export const normalizeCardReference = (value: string) => value.trim().toUpperCase();
export const validCardReference = (value: string) => /^PC-[0-9A-F]{32}$/.test(normalizeCardReference(value));
export async function customerOperationsRequest<T>(path: string, request: typeof fetch = fetch, signal?: AbortSignal): Promise<T> {
  const response = await request('/internal/customer-operations' + path, { cache: 'no-store', signal });
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'service_unavailable');
  return data as T;
}
export function customerOperationsError(error: unknown, language: Language) {
  const t = customerOperationsCopy[language];
  const code = error instanceof Error ? error.message : '';
  return ({ customer_not_found: t.notFound, card_not_found: t.cardNotFound, invalid_card_reference: t.invalidCard,
    invalid_customer_reference: t.notFound, trace_inconsistent: t.inconsistent, invalid_search: t.invalidSearch,
    invalid_input: t.invalidSearch, authentication_required: t.auth, staff_required: t.auth } as Record<string, string>)[code] ?? t.error;
}
