# AGENTS.md — Localized AI Video Ad Pipeline (Non-English D2C)

## 1. Monorepo Structure
- `/services/worker` — Python + FastAPI + Celery + Vertex AI (`veo-3.1-generate-001`) + FFmpeg
- `/packages/remotion` — TypeScript + Remotion (RTL Arabic/Urdu animated caption templates)
- `/apps/studio` — Next.js + Tailwind CSS v4 + Supabase Auth & Credit Ledger

## 2. Sub-Agent Delegation Rules
- **Sub-Agent 1 (`pipeline-agent`):** Owns `/services/worker`. Implements atomic credit deduction, Veo 3.1 GCS job dispatch, and TTS voiceover generation.
- **Sub-Agent 2 (`remotion-agent`):** Owns `/packages/remotion`. Builds 9:16 vertical ad templates with RTL/Nastaliq font rendering and price/CTA overlays.
- **Sub-Agent 3 (`studio-agent`):** Owns `/apps/studio`. Builds dark-mode creator studio, product URL scraper, credit checkout, and MP4 download gallery.

## 3. Mandatory Verification Gates
1. `cd services/worker && ruff check . && pytest`
2. `cd packages/remotion && npm run typecheck && npm run lint`
3. `cd apps/studio && npm run typecheck && npm run lint && npm run build`
