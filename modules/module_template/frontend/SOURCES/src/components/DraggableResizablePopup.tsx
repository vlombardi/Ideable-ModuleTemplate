import { useState, useRef, useCallback, useEffect, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { X } from 'lucide-react'

interface DraggableResizablePopupProps {
  title: string
  onClose: () => void
  children: ReactNode
  initialWidth?: number
  initialHeight?: number
  minWidth?: number
  minHeight?: number
  maxWidth?: number
  maxHeight?: number
  closeOnBackdrop?: boolean
  fillContent?: boolean
}

export default function DraggableResizablePopup({
  title,
  onClose,
  children,
  initialWidth = 900,
  initialHeight = 600,
  minWidth = 320,
  minHeight = 200,
  maxWidth = 1600,
  maxHeight = 1000,
  closeOnBackdrop = true,
  fillContent = false,
}: DraggableResizablePopupProps) {
  const [position, setPosition] = useState({ x: 0, y: 0 })
  const [size, setSize] = useState({ width: initialWidth, height: initialHeight })
  const [isDragging, setIsDragging] = useState(false)
  const [isResizing, setIsResizing] = useState(false)
  const dragStart = useRef({ x: 0, y: 0, posX: 0, posY: 0 })
  const resizeStart = useRef({ x: 0, y: 0, w: 0, h: 0 })

  useEffect(() => {
    const clampedWidth = Math.min(maxWidth, window.innerWidth - 40)
    const clampedHeight = Math.min(maxHeight, window.innerHeight - 40)
    const w = Math.min(initialWidth, clampedWidth)
    const h = Math.min(initialHeight, clampedHeight)
    setSize({ width: w, height: h })
    setPosition({
      x: Math.max(0, (window.innerWidth - w) / 2),
      y: Math.max(0, (window.innerHeight - h) / 2),
    })
  }, [])

  const handleDragStart = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault()
      dragStart.current = { x: e.clientX, y: e.clientY, posX: position.x, posY: position.y }
      setIsDragging(true)
    },
    [position],
  )

  useEffect(() => {
    if (!isDragging) return
    const handleMouseMove = (e: MouseEvent) => {
      const dx = e.clientX - dragStart.current.x
      const dy = e.clientY - dragStart.current.y
      const newX = Math.max(
        0,
        Math.min(window.innerWidth - size.width, dragStart.current.posX + dx),
      )
      const newY = Math.max(
        0,
        Math.min(window.innerHeight - 40, dragStart.current.posY + dy),
      )
      setPosition({ x: newX, y: newY })
    }
    const handleMouseUp = () => setIsDragging(false)
    window.addEventListener('mousemove', handleMouseMove)
    window.addEventListener('mouseup', handleMouseUp)
    return () => {
      window.removeEventListener('mousemove', handleMouseMove)
      window.removeEventListener('mouseup', handleMouseUp)
    }
  }, [isDragging, size.width])

  const handleResizeStart = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault()
      e.stopPropagation()
      resizeStart.current = { x: e.clientX, y: e.clientY, w: size.width, h: size.height }
      setIsResizing(true)
    },
    [size],
  )

  useEffect(() => {
    if (!isResizing) return
    const handleMouseMove = (e: MouseEvent) => {
      const dw = e.clientX - resizeStart.current.x
      const dh = e.clientY - resizeStart.current.y
      const newWidth = Math.max(
        minWidth,
        Math.min(maxWidth, window.innerWidth - position.x, resizeStart.current.w + dw),
      )
      const newHeight = Math.max(
        minHeight,
        Math.min(maxHeight, window.innerHeight - position.y, resizeStart.current.h + dh),
      )
      setSize({ width: newWidth, height: newHeight })
    }
    const handleMouseUp = () => setIsResizing(false)
    window.addEventListener('mousemove', handleMouseMove)
    window.addEventListener('mouseup', handleMouseUp)
    return () => {
      window.removeEventListener('mousemove', handleMouseMove)
      window.removeEventListener('mouseup', handleMouseUp)
    }
  }, [isResizing, minWidth, minHeight, maxWidth, maxHeight, position.x, position.y])

  const scopeElement = typeof document !== 'undefined' ? document.querySelector('.template-scope') : null
  const portalTarget = typeof document !== 'undefined'
    ? (document.body || document.getElementById('root'))
    : null
  if (!portalTarget) return null
  const scopeDataLf = scopeElement?.getAttribute('data-lf') ?? undefined

  return createPortal(
    <div className="template-scope" data-lf={scopeDataLf}>
      <div
        className="template:fixed template:inset-0 template:z-50 template:bg-black/80"
        onClick={closeOnBackdrop ? onClose : undefined}
      >
        <div
          className="template:absolute template:bg-white template:rounded-lg template:border template:shadow-lg template:flex template:flex-col template:overflow-hidden"
          style={{
            left: position.x,
            top: position.y,
            width: size.width,
            height: size.height,
          }}
          onClick={(e) => e.stopPropagation()}
        >
          <div
            className="template:flex template:items-center template:justify-between template:px-6 template:py-4 template:border-b template:cursor-move template:select-none template:shrink-0"
            onMouseDown={handleDragStart}
          >
            <h2 className="template:text-lg template:font-semibold">{title}</h2>
            <button
              type="button"
              onClick={onClose}
              className="template:inline-flex template:h-8 template:w-8 template:items-center template:justify-center template:rounded-md template:border hover:template:bg-accent"
            >
              <X className="template:h-4 template:w-4" />
            </button>
          </div>

          <div className={fillContent ? 'template:flex-1 template:overflow-hidden' : 'template:flex-1 template:overflow-auto template:p-6'}>
            {children}
          </div>

          <div
            className="template:absolute template:bottom-0 template:right-0 template:w-4 template:h-4 template:cursor-se-resize"
            onMouseDown={handleResizeStart}
          >
            <svg viewBox="0 0 16 16" className="template:w-full template:h-full template:text-muted-foreground">
              <path fill="currentColor" d="M16 16L8 16L16 8Z" />
            </svg>
          </div>
        </div>
      </div>
    </div>,
    portalTarget,
  )
}
