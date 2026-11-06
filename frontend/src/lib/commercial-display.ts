/** Presentation-only repair of known synthetic labels. Never alter persisted snapshots. */
export function displayCommercialText(value: string): string {
  const repairs = [
    ['FICTIF ? STRIPE TEST', 'FICTIF — STRIPE TEST'],
    ['FICTIONAL ? STRIPE TEST', 'FICTIONAL — STRIPE TEST'],
    ['aucun grading r?el.', 'aucun grading réel.'],
    ['Fiscalit? synth?tique TEST 0 %, sans valeur fiscale.', 'Fiscalité synthétique TEST 0 %, sans valeur fiscale.'],
    ['Simulation uniquement : aucune couverture r?elle.', 'Simulation uniquement : aucune couverture réelle.'],
    ['Aucun transport ni remboursement r?el. Ne pas envoyer de cartes.', 'Aucun transport ni remboursement réel. Ne pas envoyer de cartes.'],
  ];
  return repairs.reduce((text, [old, replacement]) => text.replaceAll(old, replacement), value);
}
