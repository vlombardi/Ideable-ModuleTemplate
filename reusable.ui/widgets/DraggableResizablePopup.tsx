import { useState, useRef, useCallback, useEffect, type ReactNode } from "react"
import { createPortal } from "react-dom"
import { X } from "lucide-react"
import { cn } from "../lib/utils"

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
  /**
   * When true, clicking the dark backdrop outside the window closes it. Defaults to
   * **false**: a popup window dismisses ONLY via its close (X) icon, so a stray click
   * outside never loses the window (and its unsaved view state). Opt in per popup if a
   * lightweight click-away is genuinely wanted.
   */
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
  closeOnBackdrop = false,
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
    window.addEventListener("mousemove", handleMouseMove)
    window.addEventListener("mouseup", handleMouseUp)
    return () => {
      window.removeEventListener("mousemove", handleMouseMove)
      window.removeEventListener("mouseup", handleMouseUp)
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
    window.addEventListener("mousemove", handleMouseMove)
    window.addEventListener("mouseup", handleMouseUp)
    return () => {
      window.removeEventListener("mousemove", handleMouseMove)
      window.removeEventListener("mouseup", handleMouseUp)
    }
  }, [isResizing, minWidth, minHeight, maxWidth, maxHeight, position.x, position.y])

  const portalTarget = typeof document !== "undefined" ? document.body : null
  if (!portalTarget) return null

  return createPortal(
    <div
      className="ideable:fixed ideable:inset-0 ideable:z-50 ideable:bg-black/80"
      onClick={closeOnBackdrop ? onClose : undefined}
    >
      <div
        className={cn(
          "ideable:absolute ideable:bg-popover ideable:text-popover-foreground ideable:rounded-lg ideable:border ideable:shadow-lg ideable:flex ideable:flex-col ideable:overflow-hidden",
        )}
        style={{
          left: position.x,
          top: position.y,
          width: size.width,
          height: size.height,
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div
          className="ideable:flex ideable:items-center ideable:justify-between ideable:px-6 ideable:py-4 ideable:border-b ideable:cursor-move ideable:select-none ideable:shrink-0"
          onMouseDown={handleDragStart}
        >
          <h2 className="ideable:text-lg ideable:font-semibold">{title}</h2>
          <button
            type="button"
            onClick={onClose}
            className="ideable:inline-flex ideable:h-8 ideable:w-8 ideable:items-center ideable:justify-center ideable:rounded-md ideable:border ideable:hover:bg-accent"
          >
            <X className="ideable:h-4 ideable:w-4" />
          </button>
        </div>

        <div className={fillContent ? "ideable:flex-1 ideable:overflow-hidden" : "ideable:flex-1 ideable:overflow-auto ideable:p-6"}>
          {children}
        </div>

        <div
          className="ideable:absolute ideable:bottom-0 ideable:right-0 ideable:w-4 ideable:h-4 ideable:cursor-se-resize"
          onMouseDown={handleResizeStart}
        >
          <svg viewBox="0 0 16 16" className="ideable:w-full ideable:h-full ideable:text-muted-foreground">
            <path fill="currentColor" d="M16 16L8 16L16 8Z" />
          </svg>
        </div>
      </div>
    </div>,
    portalTarget,
  )
}
