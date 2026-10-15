import { currentCustomer } from "@/lib/server-customer";
import { AccountArea } from "@/components/account-area";

export default async function Account() {
  const result = await currentCustomer();
  if (result.status !== "authenticated") return null;
  return <AccountArea customer={result.customer} />;
}
