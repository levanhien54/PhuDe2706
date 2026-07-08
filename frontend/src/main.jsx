import { StrictMode, Component } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.jsx'

// Top-level error boundary: one bad API response or render error inside App must not blank the
// whole app to a white screen. Catches render/lifecycle errors and offers a reload affordance.
class ErrorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { error: null }
  }

  static getDerivedStateFromError(error) {
    return { error }
  }

  componentDidCatch(error, info) {
    console.error('[App] render error:', error, info)
  }

  render() {
    if (this.state.error) {
      return (
        <div style={{ padding: '40px', color: '#e2e8f0', fontFamily: 'sans-serif', maxWidth: '640px', margin: '0 auto' }}>
          <h2>⚠️ Đã xảy ra lỗi hiển thị</h2>
          <p style={{ color: '#94a3b8' }}>Giao diện gặp sự cố ngoài dự kiến. Vui lòng tải lại ứng dụng.</p>
          <pre style={{ whiteSpace: 'pre-wrap', color: '#f87171', fontSize: '0.8rem' }}>{String(this.state.error?.message || this.state.error)}</pre>
          <button className="btn btn-primary" onClick={() => window.location.reload()} style={{ marginTop: '12px' }}>Tải lại</button>
        </div>
      )
    }
    return this.props.children
  }
}

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </StrictMode>,
)
