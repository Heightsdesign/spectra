import "server-only";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { loadCustomer } from "./customer";

export async function currentCustomer() {
  const cookie = (await cookies()).toString();
  const result = await loadCustomer(cookie, process.env.SPECTRA_BACKEND_URL ?? "http://127.0.0.1:8000");
  if (result.status === "unauthorized") redirect("/login");
  return result;
}
