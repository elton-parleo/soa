import { useState } from 'react'
import { supabase } from '../supabase.js'

export default function LoginPage() {
  const [loading, setLoading] = useState(false)
  const [error,   setError]   = useState(null)

  async function handleGoogleSignIn() {
    setLoading(true)
    setError(null)
    try {
      const { error } = await supabase.auth.signInWithOAuth({
        provider: 'google',
        options: {
          redirectTo: window.location.origin,
          queryParams: {
            // Request offline access for refresh token support
            access_type: 'offline',
            prompt: 'select_account',
          },
        },
      })
      if (error) {
        setError('Sign in failed. Please try again.')
        setLoading(false)
      }
      // If no error, browser is redirecting to Google — keep loading=true
    } catch (err) {
      setError('Sign in failed. Please try again.')
      setLoading(false)
    }
  }

  return (
    <div style={{
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      minHeight: '100vh',
      background: '#F1F5F9',
      fontFamily: "'DM Sans', sans-serif",
    }}>
      {/* Card */}
      <div style={{
        background: '#FFFFFF',
        borderRadius: 12,
        padding: '40px 44px 44px',
        width: 400,
        boxShadow: '0 4px 24px rgba(0,0,0,0.08), 0 1px 4px rgba(0,0,0,0.04)',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
      }}>

        {/* Parleo logo + wordmark */}
        <div style={{
          display: 'flex',
          alignItems: 'center',
          gap: '8px',
          marginBottom: '32px',
          justifyContent: 'center',
        }}>
          <svg
            width="28"
            height="28"
            viewBox="0 0 24 24"
            fill="none"
          >
            <rect
              x="2" y="2"
              width="8" height="20"
              rx="1.5"
              fill="hsl(213,99%,50%)"
            />
            <rect
              x="14" y="6"
              width="8" height="12"
              rx="1.5"
              fill="hsl(213,99%,50%)"
              opacity="0.4"
            />
          </svg>
          <span style={{
            fontSize: '22px',
            fontWeight: '700',
            color: '#0F172A',
            letterSpacing: '0.04em',
            fontFamily: "'DM Sans', sans-serif",
          }}>
            PARLEO
          </span>
        </div>

        {/* Welcome text */}
        <div style={{
          textAlign: 'center',
          marginBottom: 24,
        }}>
          <div style={{ fontSize: 18, fontWeight: 700, color: '#0F172A' }}>
            Welcome back
          </div>
        </div>

        {/* Sign in button */}
        <button
          onClick={handleGoogleSignIn}
          disabled={loading}
          style={{
            width: '100%',
            height: 44,
            background: loading ? '#F8FAFC' : '#FFFFFF',
            border: '1.5px solid #E2E8F0',
            borderRadius: 8,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: 10,
            fontSize: 15,
            fontWeight: 500,
            color: '#0F172A',
            cursor: loading ? 'not-allowed' : 'pointer',
            opacity: loading ? 0.7 : 1,
            transition: 'background 0.15s, border-color 0.15s, box-shadow 0.15s',
            fontFamily: "'DM Sans', sans-serif",
          }}
          onMouseEnter={e => {
            if (!loading) {
              e.currentTarget.style.background   = '#F8FAFC'
              e.currentTarget.style.borderColor  = '#CBD5E1'
              e.currentTarget.style.boxShadow    = '0 1px 4px rgba(0,0,0,0.06)'
            }
          }}
          onMouseLeave={e => {
            if (!loading) {
              e.currentTarget.style.background   = '#FFFFFF'
              e.currentTarget.style.borderColor  = '#E2E8F0'
              e.currentTarget.style.boxShadow    = 'none'
            }
          }}
        >
          {/* Google G logo */}
          <svg width="18" height="18" viewBox="0 0 18 18">
            <path fill="#4285F4"
              d="M17.64 9.2c0-.637-.057-1.251-.164-1.84H9v3.481h4.844c-.209 1.125-.843 2.078-1.796 2.717v2.258h2.908c1.702-1.567 2.684-3.874 2.684-6.615z"/>
            <path fill="#34A853"
              d="M9 18c2.43 0 4.467-.806 5.956-2.18l-2.908-2.259c-.806.54-1.837.86-3.048.86-2.344 0-4.328-1.584-5.036-3.711H.957v2.332C2.438 15.983 5.482 18 9 18z"/>
            <path fill="#FBBC05"
              d="M3.964 10.71c-.18-.54-.282-1.117-.282-1.71s.102-1.17.282-1.71V4.958H.957C.347 6.173 0 7.548 0 9s.348 2.827.957 4.042l3.007-2.332z"/>
            <path fill="#EA4335"
              d="M9 3.58c1.321 0 2.508.454 3.44 1.345l2.582-2.58C13.463.891 11.426 0 9 0 5.482 0 2.438 2.017.957 4.958L3.964 7.29C4.672 5.163 6.656 3.58 9 3.58z"/>
          </svg>
          {loading ? 'Signing in…' : 'Sign in with Google'}
        </button>

        {/* Error state */}
        {error && (
          <div style={{
            marginTop: 16,
            background: '#FEE2E2',
            border: '1px solid #FECACA',
            borderRadius: 6,
            padding: '10px 14px',
            fontSize: 13,
            color: '#991B1B',
            textAlign: 'center',
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            width: '100%',
            boxSizing: 'border-box',
          }}>
            <span style={{ color: '#DC2626', flexShrink: 0 }}>✕</span>
            {error}
          </div>
        )}
      </div>
    </div>
  )
}
