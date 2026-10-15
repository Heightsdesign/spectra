import 'server-only';
import { cache } from 'react';
import { cookies } from 'next/headers';
import { redirect } from 'next/navigation';

export const currentStaff = cache(async (): Promise<{ language: 'FR' | 'EN'; role: string } | null> => {
  let response: Response;
  try {
    response = await fetch(`${process.env.SPECTRA_BACKEND_URL ?? 'http://127.0.0.1:8000'}/internal/intake/me`, {
      headers: { Cookie: (await cookies()).toString() }, cache: 'no-store',
    });
  } catch { return null; }
  if (response.status === 401) redirect('/login');
  if (response.status === 403) redirect('/account');
  if (!response.ok) return null;
  return response.json();
});
