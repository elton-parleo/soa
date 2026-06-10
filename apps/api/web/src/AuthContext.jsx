import { createContext, useContext, useEffect, useState } from 'react'
import { supabase } from './supabase.js'
import { setApiToken } from './api.js'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [session, setSession] = useState(undefined)
  // session === undefined → still initialising (show loading spinner)
  // session === null      → confirmed no session (show login page)
  // session is object    → confirmed session (show main app)

  useEffect(() => {
    // onAuthStateChange is the single source of truth for session state.
    //
    // It fires in three situations:
    //   1. On mount with current session from localStorage (existing
    //      session across page reloads)
    //   2. After OAuth redirect when Supabase parses the URL hash
    //      (the situation that was broken by the async session-lookup race)
    //   3. On sign out
    //
    // IMPORTANT: Do not call the auth session lookup API separately.
    // Doing so races with URL hash parsing after OAuth redirect and
    // returns null too early, causing the login redirect loop.
    const { data: { subscription } } = supabase.auth.onAuthStateChange(
      (event, session) => {
        // Update the api.js token store synchronously before setting
        // React state. This ensures the token is available for any API
        // calls triggered by the session change — including the first
        // render after OAuth redirect.
        setApiToken(session?.access_token ?? null)
        setSession(session)
      }
    )

    // Cleanup on unmount
    return () => subscription.unsubscribe()
  }, [])

  const signOut = async () => {
    setApiToken(null)
    await supabase.auth.signOut()
    // onAuthStateChange fires SIGNED_OUT and sets session to null automatically
  }

  return (
    <AuthContext.Provider
      value={{
        session,
        signOut,
        // Expose token directly so consumers can read it without calling
        // the Supabase session lookup API asynchronously
        accessToken: session?.access_token ?? null,
      }}
    >
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
