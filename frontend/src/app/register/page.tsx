import { AuthPage } from "@/components/auth-page";
export const metadata = { title: "Créer un compte / Create an account", robots: { index: false } };
export default function Register() { return <AuthPage mode="register" />; }
