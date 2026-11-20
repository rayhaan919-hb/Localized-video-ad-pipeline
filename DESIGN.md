# Modern Minimalistic UI & Design Tokens (`DESIGN.md`)

## Core Aesthetic Rules (Strict)
1. **No AI Clutter:** Avoid rainbow gradients, heavy drop shadows, or unnecessary glassmorphism. Use flat tonal surfaces with crisp `1px` borders (`#E2E8F0` light / `#27272A` dark).
2. **Typography:** `Inter` (UI) + `JetBrains Mono` (IDs, timestamps, currency, API keys). Use `tabular-nums` on all numbers.
3. **Spacing Scale:** Strictly use `4px`, `8px`, `12px`, `16px`, `24px`, `32px`. Max container width: `1200px`.
4. **States:** Every data-fetching view MUST implement:
   - Skeleton loader (matching exact layout dimensions)
   - Actionable empty state (icon + 1-line explanation + primary CTA button)
   - Inline error banner with a "Retry" button

## Brand & Color Tokens (Creamy White & Botanical Green Studio — `apps/studio/src/app/globals.css`)
> Authoritative UI specification & state matrix: see [`docs/DESIGN.md`](./docs/DESIGN.md).

- `--bg-canvas`: `#FAF7F2` (Warm creamy-white page canvas)
- `--bg-surface`: `#FFFFFF` (Primary crisp white card surface)
- `--bg-elevated`: `#F4EFE6` (Soft cream inset surface)
- `--border-dark`: `#E6E0D5` / `--border-strong`: `#D6CEC0`
- `--accent-solid`: `#15803D` (`#166534` hover, `#F0FDF4` soft tint)
- `--text-primary`: `#1C1917` / `--text-muted`: `#57534E` / `--text-placeholder`: `#6E6A63`
- **Layout:** Left `Create Video Ad` config panel (`372px`: Product Storefront URL, Language, Format/Duration/Style, Custom Video Prompt, Hook/Captions/Promo/CTA) + Center `9:16`/`16:9` Remotion `4.0.545` Player + Recent Videos gallery.
