# Localized AI Video Ad Pipeline (Non-English D2C)

A full-stack monorepo for generating localized 9:16 vertical AI video ads in **Urdu (`ur`)**, **Arabic (`ar`)**, **Hindi (`hi`)**, and **English (`en`)** with atomic credit ledger accounting, Vertex AI Veo 3.1 (`veo-3.1-generate-001`) dispatch + offline CI fixture compositing, synthesized TTS voiceover, and Remotion RTL/Nastaliq animated caption templates.

## Monorepo Structure

- **`/services/worker`** — Python + FastAPI + Celery + Vertex AI (`veo-3.1-generate-001`) + FFmpeg
  - Atomic credit deduction (`UPDATE workspaces SET credit_balance = credit_balance - 1 WHERE id = :id AND credit_balance >= 1`) and automatic 1-credit refund on job failure
  - Product URL metadata scraper (`/v1/products/scrape`)
  - Localized script & 16-bit PCM `.wav` TTS voiceover generator
  - Offline mock mode (`MOCK_VERTEX_VEO=true`) that maintains a 2-second 9:16 sample `.mp4` fixture (`services/worker/fixtures/sample_9_16.mp4`) and composites it with TTS audio into `services/worker/static/renders/<job_id>.mp4`
- **`/packages/remotion`** (`@video-ad/remotion`) — TypeScript + Remotion
  - 9:16 vertical ad composition (`1080×1920`, `30fps`, `60` frames)
  - RTL typography (`Noto Nastaliq Urdu` with `1.85` line-height for Urdu, `Noto Sans Arabic` for Arabic) and LTR typography (`Noto Sans Devanagari` for Hindi, `Inter` for English)
  - Word-highlighted animated captions, `JetBrains Mono` (`tabular-nums`) price badges, and localized CTA overlays
- **`/apps/studio`** (`@video-ad/studio`) — Next.js + Tailwind CSS v4 + Supabase Auth & Credit Ledger
  - Dark-mode creator studio adhering strictly to `DESIGN.md` (`#09090B` canvas, `#18181B` surface, `1px solid #27272A` borders, `#6366F1` Indigo accent, `Inter` + `JetBrains Mono` with `tabular-nums`)
  - `360px` Left Input Panel (Product URL scraper, Target Language, Ad Angle, live script editor) + Center 9:16 Remotion `<Player />` stage + Bottom Render Queue & MP4 Download Gallery
  - Implements Skeleton Loaders, Actionable Empty States, and Inline Error Banners with Retry buttons across all data-fetching views

## Mandatory Verification Gates

```bash
# 1. Worker (Ruff + Pytest)
cd services/worker && ruff check . && pytest

# 2. Remotion Package (TypeScript + ESLint)
cd packages/remotion && npm run typecheck && npm run lint

# 3. Creator Studio (TypeScript + ESLint + Next.js Production Build)
cd apps/studio && npm run typecheck && npm run lint && npm run build
```
