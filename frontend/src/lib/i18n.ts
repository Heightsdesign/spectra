export type Language = "FR" | "EN";
export function language(value: unknown): Language { return value === "EN" ? "EN" : "FR"; }

export const messages = {
  FR: {
    register: "Créer un compte", login: "Se connecter", verify: "Vérifier mon adresse e-mail", forgot: "Mot de passe oublié", reset: "Réinitialiser le mot de passe",
    intro: "Un espace pour votre collection et vos soumissions.",
    first_name: "Prénom", last_name: "Nom", email: "Adresse e-mail", password: "Mot de passe", confirm: "Confirmer le mot de passe", preferred_language: "Langue préférée", current_password: "Mot de passe actuel", new_password: "Nouveau mot de passe",
    passwordHint: "Entre 12 et 128 caractères. Utilisez un mot de passe long et unique.",
    busy: "Traitement en cours…", check_email: "Si votre demande est éligible, un e-mail contenant un lien vous sera envoyé. Vérifiez votre messagerie.",
    email_verified: "Adresse vérifiée. Vous pouvez maintenant vous connecter.", password_reset: "Mot de passe réinitialisé. Veuillez vous reconnecter.", password_changed: "Mot de passe modifié. Toutes les sessions sont fermées. Veuillez vous reconnecter.",
    invalid_credentials: "Connexion impossible. Vérifiez vos identifiants et la vérification de votre adresse e-mail.", invalid_input: "Vérifiez les champs du formulaire.",
    invalid_or_expired_token: "Ce lien est invalide, expiré ou déjà utilisé. Demandez un nouveau lien.", rate_limited: "Trop de tentatives. Réessayez plus tard.", csrf_failed: "La session a changé. Rechargez la page et réessayez.",
    authentication_required: "Votre session a expiré. Veuillez vous reconnecter.", invalid_current_password: "Le mot de passe actuel est incorrect.",
    unavailable: "Le service est temporairement indisponible. Réessayez plus tard.", mismatch: "Les mots de passe ne correspondent pas.", missingToken: "Ouvrez le lien reçu par e-mail pour continuer.",
    resend: "Recevoir un nouveau lien de vérification", account: "Mon compte", welcome: "Bienvenue", settings: "Paramètres du compte", logout: "Se déconnecter", save: "Enregistrer les modifications", saved: "Vos préférences ont été enregistrées.",
    submissions: "Mes soumissions", cards: "Mes cartes gradées", comingSoon: "Bientôt disponible", empty: "La consultation des cartes gradées sera disponible ultérieurement.",
    changePassword: "Modifier le mot de passe", verified: "Adresse e-mail vérifiée", emailFixed: "Le changement d’adresse e-mail n’est pas encore disponible.", back: "Retour au compte", languageLabel: "Langue de l’interface", serviceDown: "Le service de compte est indisponible. Réessayez plus tard.",
  },
  EN: {
    register: "Create an account", login: "Sign in", verify: "Verify my email", forgot: "Forgot password", reset: "Reset password",
    intro: "A space for your collection and submissions.",
    first_name: "First name", last_name: "Last name", email: "Email address", password: "Password", confirm: "Confirm password", preferred_language: "Preferred language", current_password: "Current password", new_password: "New password",
    passwordHint: "12–128 characters. Choose a long, unique password.", busy: "Working…",
    check_email: "If your request is eligible, an email with a link will be sent. Please check your inbox.", email_verified: "Email verified. You can now sign in.", password_reset: "Password reset. Please sign in again.", password_changed: "Password changed. All sessions are signed out. Please sign in again.",
    invalid_credentials: "Unable to sign in. Check your credentials and that your email has been verified.", invalid_input: "Check the form fields.",
    invalid_or_expired_token: "This link is invalid, expired or already used. Request a new link.", rate_limited: "Too many attempts. Please try again later.", csrf_failed: "Your session changed. Reload this page and try again.", authentication_required: "Your session expired. Please sign in again.", invalid_current_password: "The current password is incorrect.",
    unavailable: "The service is temporarily unavailable. Please try again later.", mismatch: "Passwords do not match.", missingToken: "Open the link from your email to continue.",
    resend: "Request a new verification link", account: "My account", welcome: "Welcome", settings: "Account settings", logout: "Sign out", save: "Save changes", saved: "Your preferences have been saved.",
    submissions: "My submissions", cards: "My graded cards", comingSoon: "Coming soon", empty: "Graded cards are not available yet.",
    changePassword: "Change password", verified: "Email verified", emailFixed: "Email address changes are not available yet.", back: "Back to account", languageLabel: "Interface language", serviceDown: "The account service is unavailable. Please try again later.",
  },
} as const;
export type MessageKey = keyof typeof messages.EN;

