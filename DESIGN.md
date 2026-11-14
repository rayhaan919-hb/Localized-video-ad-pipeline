# Modern Minimalistic UI & Design Tokens (`DESIGN.md`)

## Core Aesthetic Rules (Strict)
1. **No AI Clutter:** Avoid rainbow gradients, heavy drop shadows, or unnecessary glassmorphism. Use flat tonal surfaces with crisp `1px` borders (`#E2E8F0` light / `#27272A` dark).
2. **Typography:** `Inter` (UI) + `JetBrains Mono` (IDs, timestamps, currency, API keys). Use `tabular-nums` on all numbers.
3. **Spacing Scale:** Strictly use `4px`, `8px`, `12px`, `16px`, `24px`, `32px`. Max container width: `1200px`.
4. **States:** Every data-fetching view MUST implement:
   - Skeleton loader (matching exact layout dimensions)
   - Actionable empty state (icon + 1-line explanation + primary CTA button)
   - Inline error banner with a "Retry" button

## Brand & Color Tokens (Dark Creator Studio)
- `--bg-canvas`: `#09090B`
- `--bg-surface`: `#18181B`
- `--accent-primary`: `#6366F1` (Indigo)
- `--text-primary`: `#FAFAFA`
- `--text-muted`: `#A1A1AA`
- **Layout:** Left input panel (`360px`: Product URL, Target Language, Ad Angle) + Center 9:16 Remotion Player preview + Bottom render queue strip.
