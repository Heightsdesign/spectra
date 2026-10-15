import { AuthPage } from "@/components/auth-page";
export const metadata = { title: "Mot de passe oublié / Forgot password", robots: { index: false } };
export default function Forgot() { return <AuthPage mode="forgot" />; }
