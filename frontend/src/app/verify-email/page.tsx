import { AuthPage } from "@/components/auth-page";
export const metadata = { title: "Vérification / Email verification", robots: { index: false }, referrer: "no-referrer" as const };
export default function Verify() { return <AuthPage mode="verify" />; }
