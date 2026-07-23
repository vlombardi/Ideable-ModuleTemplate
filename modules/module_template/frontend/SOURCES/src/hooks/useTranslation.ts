import { useCallback, useEffect, useState } from "react"
import enMessages from "../i18n/en.json"
import itMessages from "../i18n/it.json"

type SupportedLanguage = "en" | "it"
type Messages = typeof enMessages

const HOSTAPP_LANGUAGE_KEY = "hostapp.language"
const HOSTAPP_LANGUAGE_EVENT = "hostapp:language-changed"
const DEFAULT_LANGUAGE: SupportedLanguage = "en"

const messageMap: Record<SupportedLanguage, Messages> = {
  en: enMessages,
  it: itMessages,
}

const SUPPORTED: SupportedLanguage[] = ["en", "it"]

function readLanguage(): SupportedLanguage {
  const stored = localStorage.getItem(HOSTAPP_LANGUAGE_KEY)
  if (stored && SUPPORTED.includes(stored as SupportedLanguage)) {
    return stored as SupportedLanguage
  }
  return DEFAULT_LANGUAGE
}

function getNestedValue(obj: Record<string, unknown>, path: string): string | undefined {
  const parts = path.split(".")
  let current: unknown = obj
  for (const part of parts) {
    if (current == null || typeof current !== "object") return undefined
    current = (current as Record<string, unknown>)[part]
  }
  return typeof current === "string" ? current : undefined
}

export function useTranslation() {
  const [language, setLanguage] = useState<SupportedLanguage>(readLanguage)

  useEffect(() => {
    const handler = (event: Event) => {
      const lang = (event as CustomEvent<{ language: string }>).detail?.language
      if (lang && SUPPORTED.includes(lang as SupportedLanguage)) {
        setLanguage(lang as SupportedLanguage)
      }
    }
    window.addEventListener(HOSTAPP_LANGUAGE_EVENT, handler)
    return () => window.removeEventListener(HOSTAPP_LANGUAGE_EVENT, handler)
  }, [])

  const t = useCallback(
    (key: string, vars?: Record<string, string>): string => {
      const messages = messageMap[language] as unknown as Record<string, unknown>
      let value = getNestedValue(messages, key)
      if (value === undefined) {
        const fallback = messageMap["en"] as unknown as Record<string, unknown>
        value = getNestedValue(fallback, key) ?? key
      }
      if (vars) {
        return value.replace(/\{\{(\w+)\}\}/g, (_, k) => vars[k] ?? `{{${k}}}`)
      }
      return value
    },
    [language],
  )

  return { t, language }
}
