import { useEffect, useRef, useState } from "react"
import { Button } from "../primitives/button"
import { useTranslation } from "../hooks/useTranslation"

/** The largest an image is drawn, in the form and in the details card. */
export const IMAGE_BOX_PX = 200

/**
 * An object URL for the bytes `load` returns, revoked when it changes or the component goes away.
 * `load` is called again when `key` changes; `undefined` means "nothing to show".
 */
function useLoadedImage(load: (() => Promise<Blob>) | undefined, key: unknown): string | null {
  const [url, setUrl] = useState<string | null>(null)
  useEffect(() => {
    if (!load) {
      setUrl(null)
      return
    }
    let cancelled = false
    let made: string | null = null
    load()
      .then((blob) => {
        if (cancelled) return
        made = URL.createObjectURL(blob)
        setUrl(made)
      })
      .catch(() => {
        if (!cancelled) setUrl(null)
      })
    return () => {
      cancelled = true
      if (made) URL.revokeObjectURL(made)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key])
  return url
}

/**
 * An image in a box of at most 200 x 200 px, its proportions kept (`object-fit: contain`).
 * Used by the details card; the form's `ImageField` draws the same box.
 */
export function EntityImage({
  load,
  cacheKey,
  alt,
}: {
  /** Fetch the image's bytes. Omit when the entity has none. */
  load?: () => Promise<Blob>
  /** Changes when the image may have changed, so it is fetched again. */
  cacheKey: unknown
  alt: string
}) {
  const { t } = useTranslation()
  const url = useLoadedImage(load, cacheKey)
  if (!load) return <span>-</span>
  if (!url) return <span className="ideable:text-xs ideable:text-muted-foreground">{t("standardPage.loadingImage")}</span>
  return (
    <img
      src={url}
      alt={alt}
      className="ideable:max-h-[200px] ideable:max-w-[200px] ideable:object-contain"
    />
  )
}

/**
 * A form field for an image: a file input with a preview and a remove action.
 *
 * Its value is what the form sends back — `File` (a new image), `false` (remove the stored one) or
 * `""`/`undefined` (unchanged). The widget never decides what is acceptable: the `accept` hint only
 * narrows the file chooser, and the SERVER judges the bytes and answers a refusal with a message the
 * form shows (`StandardEntityPage`).
 */
export function ImageField({
  id,
  value,
  onChange,
  load,
  cacheKey,
  accept,
  disabled,
  label,
}: {
  id: string
  value: unknown
  onChange: (next: File | false | "") => void
  /** Fetch the STORED image, when the row has one. */
  load?: () => Promise<Blob>
  cacheKey: unknown
  accept?: string
  disabled?: boolean
  label: string
}) {
  const { t } = useTranslation()
  const input = useRef<HTMLInputElement>(null)
  const chosen = value instanceof File ? value : null
  const removed = value === false
  const stored = useLoadedImage(!chosen && !removed ? load : undefined, cacheKey)
  const [preview, setPreview] = useState<string | null>(null)
  useEffect(() => {
    if (!chosen) {
      setPreview(null)
      return
    }
    const made = URL.createObjectURL(chosen)
    setPreview(made)
    return () => URL.revokeObjectURL(made)
  }, [chosen])
  const shown = preview ?? stored
  const hasImage = Boolean(chosen) || (!removed && Boolean(load))

  return (
    <div className="ideable:flex ideable:flex-col ideable:gap-2">
      {shown ? (
        <img
          src={shown}
          alt={label}
          className="ideable:max-h-[200px] ideable:max-w-[200px] ideable:object-contain"
        />
      ) : (
        <span className="ideable:text-sm ideable:text-muted-foreground">
          {removed ? t("standardPage.imageRemoved") : t("standardPage.noImage")}
        </span>
      )}
      <input
        ref={input}
        id={id}
        type="file"
        accept={accept}
        disabled={disabled}
        className="ideable:text-sm"
        onChange={(event) => {
          const file = event.target.files?.[0]
          if (file) onChange(file)
        }}
      />
      {hasImage && (
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={disabled}
          onClick={() => {
            if (input.current) input.current.value = ""
            onChange(chosen ? "" : false)
          }}
        >
          {t("standardPage.removeImage")}
        </Button>
      )}
    </div>
  )
}
