import React, { lazy, Suspense } from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import TemplateItems from './pages/TemplateItems'
import './index.css'

// Dev-only gallery: lazily loaded and gated so WIDGET_EXAMPLES=false builds
// tree-shake the page (and its heavy deps) out entirely.
const WidgetGallery = __WIDGET_EXAMPLES__ ? lazy(() => import('./pages/WidgetGallery')) : null

const lfMode = import.meta.env.VITE_TEMPLATE_LF_MODE === 'module' ? 'module' : 'hostapp'

function App() {
  return (
    <div
      className="template-scope template:min-h-screen template:bg-background template:p-6"
      data-lf={lfMode}
    >
      <Routes>
        <Route path="/template/items" element={<TemplateItems />} />
        {__WIDGET_EXAMPLES__ && WidgetGallery && (
          <Route
            path="/template/gallery"
            element={
              <Suspense fallback={null}>
                <WidgetGallery />
              </Suspense>
            }
          />
        )}
        <Route path="*" element={<Navigate to="/template/items" replace />} />
      </Routes>
    </div>
  )
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </React.StrictMode>,
)
