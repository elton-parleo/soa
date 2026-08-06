import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.jsx'
// V4 design tokens (custom properties + reduced-motion/scroll/grain
// rules) — global, since every entry (dashboard, /lite, audit landing,
// audit report, /bots) shares this one main.jsx.
import './ds/tokens.css'

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
)
