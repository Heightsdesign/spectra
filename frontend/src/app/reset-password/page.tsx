import { AuthPage } from "@/components/auth-page";
export const metadata = { title: "Nouveau mot de passe / Reset password", robots: { index: false }, referrer: "no-referrer" as const };
export default function Reset() { return <AuthPage mode="reset" />; }
