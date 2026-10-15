import { AuthPage } from "@/components/auth-page";
export const metadata = { title: "Connexion / Sign in", robots: { index: false } };
export default function Login() { return <AuthPage mode="login" />; }
