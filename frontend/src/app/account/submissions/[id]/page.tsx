import { currentCustomer } from '@/lib/server-customer';
import { SubmissionPage } from '@/components/submissions';
export default async function Detail({params}:{params:Promise<{id:string}>}) {
 const result=await currentCustomer();
 if(result.status!=='authenticated')return null;
 const {id}=await params;
 return <SubmissionPage lang={result.customer.preferred_language} identifier={id}/>;
}
