import { createClient } from '@supabase/supabase-js'

const supabaseUrl     = import.meta.env.VITE_SUPABASE_URL
const supabaseAnonKey = import.meta.env.VITE_SUPABASE_ANON_KEY

if (!supabaseUrl || !supabaseAnonKey) {
  console.error(
    'Missing Supabase environment variables.',
    'Ensure VITE_SUPABASE_URL and',
    'VITE_SUPABASE_ANON_KEY are set in',
    '.env.local (dev) or Vercel (prod).'
  )
}

export const supabase = createClient(
  supabaseUrl,
  supabaseAnonKey,
  {
    auth: {
      // Persist session across page reloads
      persistSession: true,
      // Automatically refresh token before it expires
      autoRefreshToken: true,
      // Detect session from URL after OAuth redirect
      // (Supabase sets #access_token in the URL hash on callback)
      detectSessionInUrl: true,
    },
  }
)
