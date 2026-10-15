export type AuthMode = "register" | "login" | "verify" | "forgot" | "reset";
export function validateAuth(mode: AuthMode, values: Record<string, string>): "invalid_input" | "mismatch" | null {
  if (["register", "login", "forgot"].includes(mode) && (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(values.email ?? "") || values.email.length > 254)) return "invalid_input";
  if (["register", "reset"].includes(mode)) {
    if (!values.password || values.password.length < 12 || values.password.length > 128) return "invalid_input";
    if (values.password !== values.confirm) return "mismatch";
  }
  if (mode === "login" && (!values.password || values.password.length > 128)) return "invalid_input";
  if (mode === "register" && [values.first_name, values.last_name].some(v => !v?.trim() || v.trim().length > 100 || /[\x00-\x1f\x7f]/.test(v))) return "invalid_input";
  return null;
}
