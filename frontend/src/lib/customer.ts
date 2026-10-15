export type Customer = { id: string; email: string; first_name: string; last_name: string; preferred_language: "FR" | "EN"; email_verified: boolean };

export async function loadCustomer(cookie: string, backend: string, request: typeof fetch = fetch): Promise<{ status: "authenticated"; customer: Customer } | { status: "unauthorized" | "unavailable" }> {
  try {
    const response = await request(`${backend}/api/auth/me`, { headers: { Cookie: cookie }, cache: "no-store" });
    if (response.status === 401) return { status: "unauthorized" };
    if (!response.ok) return { status: "unavailable" };
    const customer = await response.json() as Customer;
    if (!customer.id || !customer.email_verified || !["FR", "EN"].includes(customer.preferred_language)) return { status: "unavailable" };
    return { status: "authenticated", customer };
  } catch { return { status: "unavailable" }; }
}
