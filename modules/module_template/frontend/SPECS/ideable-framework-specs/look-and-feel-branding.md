# Look & Feel and Branding — what to change, when

> Framework-shared reference. It explains **how to change the application's Look & Feel** (colors, radius, fonts, logo, background) and **who changes what, at which stage**. It complements `framework-css-classes-reference.md` (the class-token catalog) and `shared-ui-specs.md` (the shared-UI contract).

## Mental model

`reusable.ui` / `@ideable/ui` is the single source of truth for UI and L&F. Every prefix (`hostapp:`, `template:` / `${APP_SLUG}:`, and the shared `ideable:`) resolves colors/radius to the **same design tokens** — `hsl(var(--token))` — so:

- **You rebrand by changing token *values*, never class names, and never by forking a widget.**
- A token you can set at **build time** (baked into the image) you can also override at **deploy time** (edited live, no rebuild).

There are therefore two knobs:

| Knob | Who | When it applies | Rebuild? |
|---|---|---|---|
| **Runtime override** — `config/theme-override.css` | Deployer / operator | Edited in the deployed folder | No |
| **Build-time defaults** — design tokens in source | Developer / maintainer | Baked into the image | Yes |

**Token value format (both knobs):** space-separated HSL, **no `hsl()` wrapper, no commas** — e.g. `--primary: 24 95% 53%;`. This matches the canonical palette in `reusable.ui/styles/base-tokens.css`.

---

## Deployer — change L&F at deploy time (no rebuild)

Edit files in the **deployed** folder. Changes take effect on a hard browser refresh — no image rebuild, no container restart (these files are served `Cache-Control: no-store`).

| To change… | Edit this deployed file |
|---|---|
| **Colors / radius / fonts (whole app)** | `deployment_root/modules/host_app/config/theme-override.css` |
| **Header logo + favicon** | `deployment_root/modules/host_app/config/favicon.png` (used for both by default) |
| **Login background** | `deployment_root/modules/host_app/config/login_bg.png` |
| **Home page content** | `deployment_root/modules/host_app/config/home.html` |

`theme-override.css` ships as an all-comments no-op scaffold — uncomment and edit:

```css
:root {
  --primary: 24 95% 53%;          /* brand / primary action color */
  --primary-foreground: 0 0% 100%;
  --background: 210 40% 98%;       /* page background */
  --card: 0 0% 100%;              /* card / table-container background */
  --radius: 0.75rem;              /* corner radius */
}
.dark {                            /* applied when <html class="dark"> */
  --primary: 24 95% 53%;
  --background: 222.2 84% 4.9%;
}
/* Custom font (asset placed alongside this file in config/):
@font-face { font-family: "BrandSans"; src: url("/config/BrandSans.woff2") format("woff2"); font-display: swap; }
body { font-family: "BrandSans", ui-sans-serif, system-ui, sans-serif; }
*/
```

Changing one token recolors host chrome **and** every `@ideable/ui` widget at once.

**Which `theme-override.css` wins.** The running application is host_app's page, so **host_app's** `config/theme-override.css` drives the shared palette for everything, including embedded remote-module widgets. A remote module's own `config/theme-override.css` only takes effect when that remote is opened **standalone** (directly, outside the host shell).

**Not runtime-changeable** (needs a rebuild): bundled icon glyphs (lucide, compiled into JS) and adding brand-new utility classes.

---

## Developer — change L&F at build time (baked into the image)

These change the shipped defaults and require rebuilding the affected frontend image(s).

| Goal | Edit | Then |
|---|---|---|
| **Default palette for everyone** (framework-wide) | `reusable.ui/styles/base-tokens.css` — `:root` / `.dark` values. **Framework-owned:** in a remote project this is read-only; request the change from the Ideable maintainer. | `npm run build:css` in `reusable.ui/`, commit `styles/compiled.css`, rebuild frontends |
| **A distinct look for *my module* while embedded in host** | your module's `src/index.css`: set `--${APP_SLUG}-module-*` values in the `.${APP_SLUG}-scope[data-lf='module']` block, and render the module root with `data-lf="module"` (module_template shows the pattern) | rebuild your module's frontend |
| **Ship a default brand for my module** | `modules/<module>/config/theme-override.css` (source) → deploys as the shipped default (deployers can still override it live) | redeploy |
| **Change a widget's structure/behavior** (beyond color) | `reusable.ui/widgets/*` or `reusable.ui/primitives/*` (framework-owned) | `npm run build:css`, rebuild |
| **One-off styling on a single page** | that page's `.tsx`, using your own prefix (`hostapp:` / `template:` / `${APP_SLUG}:`) | rebuild |

**Rules for developers:**
- Rebrand by changing token **values**, never class names.
- Import shared widgets/primitives from `@ideable/ui`; never fork or hand-roll a table/popup/dialog/chart/primitive.
- Module-scoped overrides must not mutate host-global selectors (`html`, `body`, `*`) — see `shared-ui-specs.md`.

---

## How the runtime override works (mechanism)

- Each frontend's `index.html` appends `config/theme-override.css` at runtime, **after** the compiled bundle. The bundle is fully `@layer`-wrapped; the override is an **unlayered** stylesheet, so it wins the cascade regardless of link order.
- nginx serves the file with an exact-match `location = /config/theme-override.css { Cache-Control: no-store }`, so live edits are never pinned by the immutable-CSS cache. A `?t=` cache-buster is also applied.
- **One-time activation:** the `index.html` + nginx hooks ship inside the image, so a single frontend build is required to enable the mechanism. Modules generated before this feature receive the hook idempotently on their next `scripts/module_only/sync-template-updates.sh` (it injects the hook only when absent, preserving customizations) — then one rebuild bakes it in. Thereafter L&F edits are fully runtime.
