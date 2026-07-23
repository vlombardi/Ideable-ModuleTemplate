import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import TemplateItems from './pages/TemplateItems'
import './index.css'

const lfMode = import.meta.env.VITE_TEMPLATE_LF_MODE === 'module' ? 'module' : 'hostapp'

function App() {
  return (
    <div
      className="template-scope template:min-h-screen template:bg-background template:p-6"
      data-lf={lfMode}
    >
      <Routes>
        <Route path="/template/items" element={<TemplateItems />} />
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
