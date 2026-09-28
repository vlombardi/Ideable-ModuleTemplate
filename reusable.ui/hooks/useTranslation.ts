import { useCallback, useEffect, useState } from 'react'
import enMessages from '../i18n/en.json'
import itMessages from '../i18n/it.json'

/**
 * @ideable/ui shared translation hook.
 *
 * Reads the active language from `localStorage['hostapp.language']` and updates
 * reactively on the `hostapp:language-changed` CustomEvent — the same contract
 * host_app broadcasts, so shared widgets stay in sync with the host language
 * without any per-module wiring. Supported languages: `en`, `it` (kept in sync).
 *
 * WHO OWNS WHICH STRING. The library owns the chrome of its own widgets (`table.*`,
 * `chart.*`, `auditTrail.*`, and the `common.*` strings widgets render) and ships it in
 * `i18n/en.json` / `i18n/it.json`, so a module that consumes a widget gets a complete,
 * translated widget without copying anything. A module owns its own page strings and
 * resolves them with its own hook.
 *
 * A MODULE OVERRIDES A WIDGET STRING BY INCLUDING THAT KEY IN ITS OWN BUNDLE — inclusion
 * IS the override, and nothing has to be declared or registered per key. A module calls
 * `registerModuleMessages` once with its bundles, and from then on every key it holds
 * wins over the library's; every key it does not hold comes from the library. That is why
 * a module must NOT copy a library string it does not mean to change: an identical copy
 * overrides nothing today and silently pins the old text the day the library changes it.
 * `modules/<m>/frontend/TESTS/test_i18n_contract.py` reports every override it finds, so
 * the set is readable rather than discovered by a string that stopped updating.
 */

type SupportedLanguage = 'en' | 'it'
type Messages = Record<string, unknown>

const HOSTAPP_LANGUAGE_KEY = 'hostapp.language'
const HOSTAPP_LANGUAGE_EVENT = 'hostapp:language-changed'
const DEFAULT_LANGUAGE: SupportedLanguage = 'en'

const SUPPORTED: SupportedLanguage[] = ['en', 'it']

const libraryMessages: Record<SupportedLanguage, Messages> = {
  en: enMessages as Messages,
  it: itMessages as Messages,
}

//: The consuming module's own bundle, once it has registered one. Empty until then, which
//: is exactly the library-only behaviour a consumer that never registers keeps.
const moduleMessages: Partial<Record<SupportedLanguage, Messages>> = {}

//: Mounted hooks, so a registration that happens after first paint still reaches the UI.
//: Registration normally runs at module scope (before anything renders) and this set is
//: then empty; it exists so that wiring it into an effect is a slower path and not a bug.
const subscribers = new Set<() => void>()

/**
 * Register the consuming module's own message bundles as the overrides for widget strings.
 *
 * Called once by the module's own `useTranslation` module (a side effect at import time),
 * which is the one file the framework guarantees every page of a module goes through.
 * Each consuming bundle is scoped to its own copy of this library: `@ideable/ui` is a
 * `file:` dependency and deliberately NOT a Module Federation shared singleton, so two
 * modules on one host_app page cannot see each other's registrations.
 */
export function registerModuleMessages(messages: Partial<Record<SupportedLanguage, Messages>>): void {
  for (const language of SUPPORTED) {
    const bundle = messages[language]
    if (bundle) {
      moduleMessages[language] = bundle
    }
  }
  subscribers.forEach((notify) => notify())
}

function getNestedValue(obj: Messages, path: string): string | undefined {
  const parts = path.split('.')
  let current: unknown = obj
  for (const part of parts) {
    if (current == null || typeof current !== 'object') return undefined
    current = (current as Record<string, unknown>)[part]
  }
  return typeof current === 'string' ? current : undefined
}

/**
 * The module's bundle first, the library's second, and the same pair again in English.
 *
 * The order is the whole contract: the module wins where it has the key, the library
 * answers where it does not. The English pair below them is the language fallback, and it
 * keeps the same precedence — a module that translated a key in `en` only still overrides
 * the library when the UI is in Italian and neither bundle has an Italian string for it.
 */
function resolve(key: string, language: SupportedLanguage): string | undefined {
  const chain: (Messages | undefined)[] = [
    moduleMessages[language],
    libraryMessages[language],
    moduleMessages[DEFAULT_LANGUAGE],
    libraryMessages[DEFAULT_LANGUAGE],
  ]
  for (const bundle of chain) {
    if (!bundle) continue
    const value = getNestedValue(bundle, key)
    if (value !== undefined) return value
  }
  return undefined
}

function readLanguage(): SupportedLanguage {
  const stored = localStorage.getItem(HOSTAPP_LANGUAGE_KEY)
  if (stored && SUPPORTED.includes(stored as SupportedLanguage)) {
    return stored as SupportedLanguage
  }
  return DEFAULT_LANGUAGE
}

export function useTranslation() {
  const [language, setLanguage] = useState<SupportedLanguage>(readLanguage)
  const [revision, setRevision] = useState(0)

  useEffect(() => {
    const handler = (event: Event) => {
      const lang = (event as CustomEvent<{ language: string }>).detail?.language
      if (lang && SUPPORTED.includes(lang as SupportedLanguage)) {
        setLanguage(lang as SupportedLanguage)
      }
    }
    window.addEventListener(HOSTAPP_LANGUAGE_EVENT, handler)
    const onRegister = () => setRevision((n) => n + 1)
    subscribers.add(onRegister)
    return () => {
      window.removeEventListener(HOSTAPP_LANGUAGE_EVENT, handler)
      subscribers.delete(onRegister)
    }
  }, [])

  const t = useCallback(
    (key: string, vars?: Record<string, string>): string => {
      const value = resolve(key, language) ?? key
      if (vars) {
        return value.replace(/\{\{(\w+)\}\}/g, (_, k) => vars[k] ?? `{{${k}}}`)
      }
      return value
    },
    // `revision` is not read inside the callback: it is what rebuilds `t` after a late
    // registration, so a component holding the previous `t` re-renders with the overrides.
    [language, revision],
  )

  return { t, language }
}
