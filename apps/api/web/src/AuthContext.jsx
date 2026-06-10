import { createContext, useContext, useEffect, useState } from 'react'
import { supabase } from './supabase.js'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [session, setSession] = useState(undefined)
  // undefined = still initialising (show loading spinner)
  // null      = confirmed no session (show login page)
  // object    = confirmed session (show main app)

  useEffect(() => {
    // onAuthStateChange is the single source of truth for session state.
    //
    // It fires in three situations:
    //   1. On mount with current session from localStorage (existing
    //      session across page reloads)
    //   2. After OAuth redirect when Supabase parses the URL hash
    //      (the situation that was broken)
    //   3. On sign out
    //
    // IMPORTANT: Do not call the auth session lookup API separately.
    // Doing so races with URL hash parsing after OAuth redirect and
    // returns null too early, causing the login redirect loop.
    const { data: { subscription } } = supabase.auth.onAuthStateChange(
      (event, session) => {
        setSession(session)
      }
    )

    // Cleanup on unmount
    return () => subscription.unsubscribe()
  }, [])

  const signOut = async () => {
    await supabase.auth.signOut()
    // onAuthStateChange fires SIGNED_OUT and sets session to null automatically
    // No need to call setSession(null) here
  }

  return (
    <AuthContext.Provider value={{ session, signOut }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
