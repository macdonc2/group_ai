import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'

// Note: StrictMode removed to prevent WebSocket double-mount issues
createRoot(document.getElementById('root')!).render(
  <App />,
)
