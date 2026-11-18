# Design Specification — Localized Video Ad Studio

**Phase:** 2 (UI/UX Design)  
**Product:** Localized Video Ad Studio (`apps/studio` + Remotion RTL compositions)  
**Standard:** WCAG 2.2 Level AA, Responsive (`320px` / `375px` / `768px` / `1280px`), Right-to-Left (Urdu Nastaliq, Arabic) & Devanagari script-safe.

---

## 1. Visual Direction
Calm editorial D2C studio—warm creamy-white `#FAF7F2` canvas, pure white rounded surfaces, botanical green `#15803D` pill actions, and uncluttered progressive disclosure framing live multi-script (`ur`, `ar`, `hi`, `en`) video previews.

---

## 2. Personas & Top 3 User Tasks

### Primary Personas
1. **Zainab — D2C Growth Marketer (Mobile-First E-Commerce Brand, Pakistan/UAE):** Imports storefront SKUs quickly, switches between Urdu/Arabic/English ad hooks, inspects RTL caption spacing before spending render credits, and downloads `9:16` / `16:9` MP4s for Meta & TikTok campaigns.
2. **Tariq — Creative Producer (Performance Agency Managing Multiple Brand Workspaces):** Operates across multiple client workspaces with strict tenant isolation, checks active job progress and refunds failed renders, and buys credit packs via Stripe when agency balances dip.

### Top 3 User Tasks
1. **Create & Render a Localized Product Video Ad:** Paste a storefront URL (or confirm brand, price, product title, and image) -> review live preview & captions -> optionally customize script/captions inside the collapsible drawer -> generate & download a rendered MP4.
2. **Switch Workspace & Manage Credits:** Select or create an isolated workspace -> view credit balance at a glance -> purchase Stripe credit packs and review credit history when needed.
3. **Track & Manage Rendered Videos:** Filter videos by status (`All`, `Completed`, `Active`, `Failed`) -> inspect live progress for active renders -> preview compositions, download signed MP4s, copy download links, cancel active renders for automatic refund, or retry failed jobs.

---

## 3. Happy & Unhappy User Flows

### Flow A: Product Input -> Live Preview -> MP4 Render
- **Happy Path:** Signed-in creator lands on Studio -> pastes `Product Storefront URL` and clicks `Fetch` (or enters product details directly) -> selects Target Language, Format (`9:16` / `16:9`), Duration (`4s` / `6s` / `8s`), and Ad Style -> checks confirmation -> clicks green `Generate 9:16 Video Ad (1 Credit)` pill -> active job progress updates cleanly in Recent Videos -> MP4 completes -> click `Download MP4` or `Preview`.
- **Unhappy Paths:**
  - *Invalid URL format on blur:* Inline validation (`role="alert"`) appears directly under `Product Storefront URL` (`Enter a URL starting with https:// or http://`) without clearing entered input.
  - *Scrape failure or blocked store:* Top status banner (`role="status"`, `aria-live="polite"`) explains the issue while keeping all product inputs editable.
  - *Missing Brand Name, Price, or Title on blur:* Inline `<p role="alert">` feedback guides correction without clearing text.
  - *Zero credits on Generate:* Primary CTA transitions cleanly to `0 Credits Remaining — Buy Credits` and opens `Credits & Billing`.
  - *Render failure:* Job card shows `Failed · Refunded` pill, refunds credit automatically, and offers `Retry`.

### Flow B: Authentication, Verification & Password Recovery
- **Happy Path:** Unauthenticated user lands -> `AuthModal` opens -> registers/signs in -> server sets HttpOnly session cookie + CSRF token -> modal closes cleanly.
- **Unhappy Paths:**
  - *Modal closed without signing in:* Warm amber banner in `<main>` provides a direct green `Sign In / Create Account` button.
  - *Invalid email or short password on blur:* Inline `<p role="alert">` message appears beneath the blurred field while preserving user input.
  - *Unverified email:* Compact amber `Verify` pill in the top bar opens the verification view.

### Flow C: Credit Checkout & Credit History
- **Happy Path:** User clicks green `Buy Credits` pill -> selects a server-verified credit pack -> clicks green checkout CTA -> completes Stripe Checkout -> returns to updated balance and credit history row.
- **Unhappy Paths:**
  - *Checkout canceled or webhook pending:* Balance stays accurate, banner explains status, and circular Sync refreshes safely without duplicate grants.

---

## 4. Information Architecture & Clutter Reduction Rules

| Area | Clutter Removed | User-Facing Result |
| :--- | :--- | :--- |
| Top Navigation | Removed technical `VEO 3.1 + REMOTION` tag, redundant `Renders X/Y` counter, and raw workspace hex IDs | Clean sticky `#FAF7F2` header with workspace switcher + `+ New`, Credits pill, green `Buy Credits` pill, Sync button, user chip |
| Create Video Ad Panel (`372px` desktop) | Moved optional `Promo Tag`, `Compare-At Price`, `Opening Hook`, `Captions`, and `Bottom CTA` behind `Customize script, captions & promo`; removed repetitive telemetry footer and multi-line badge noise | Focused 4-field creation workflow above confirmation CTA while keeping 100% caption customization accessible in 1 click |
| Live Preview Stage | Removed 4-box telemetry grid (`LINE HEIGHT`, `DIRECTION`), `Render Output & Storage` URI card, duplicate Generate button, and bottom draft bar | Immediate `9:16` / `16:9` Remotion Player alongside a concise 1-line summary bar and clean Urdu/RTL-safe Captions cards |
| Recent Videos Gallery | Hid raw GCS/storage URI strings; showed 4-step pipeline tracker only while a video is actively rendering | Scannable white cards with semantic `rounded-full` status pills (`Completed`, `In Progress`, `Failed · Refunded`) and pill buttons |
| Modals (`Auth` & `Credits & Billing`) | Removed raw workspace UUID banner and webhook jargon (`ATOMIC LEDGER`, `IDEMPOTENT WEBHOOK GRANTS`) | Spacious creamy-white / white `rounded-3xl` dialogs with pill buttons and horizontal-scroll-contained tables |

---

## 5. WCAG 2.2 Level AA Design Tokens (`apps/studio/src/app/globals.css`)

| Token | Value | Purpose | Contrast Verification |
| :--- | :--- | :--- | :--- |
| `--bg-canvas` | `#FAF7F2` | Warm creamy-white page canvas | Base background |
| `--bg-surface` | `#FFFFFF` | Primary cards & elevated surfaces | Crisp white elevation |
| `--bg-elevated` | `#F4EFE6` | Segmented tracks & subtle inset pills | Warm cream inset |
| `--border-dark` | `#E6E0D5` | Hairline card & divider borders | Warm neutral divider |
| `--border-strong` | `#D6CEC0` | Form control borders | Clear UI boundary |
| `--text-primary` | `#1C1917` | Headings, body & input values | `16.2:1` on cream, `17.4:1` on white |
| `--text-muted` | `#57534E` | Secondary labels & timestamps | `7.09:1` on cream, `7.55:1` on white |
| `--text-placeholder` | `#6E6A63` | Accessible input placeholders | `4.72:1` on inset, `5.38:1` on white |
| `--accent-solid` | `#15803D` | Primary green pill buttons & active tabs | `5.01:1` white `#FFFFFF` text on `#15803D` |
| `--accent-solid-hover` | `#166534` | Primary green hover fill | `7.10:1` white `#FFFFFF` text |
| `--accent-text` | `#166534` | Green icons, prices & positive deltas on light bg | `7.10:1` on white, `6.67:1` on cream |
| `--accent-soft` | `#F0FDF4` | Soft green highlight chips & success banners | Tint with `#BBF7D0` border |
| `--status-success` | `#15803D` | Completed pills & confirmed indicators | Semantic success (`#F0FDF4` bg) |
| `--status-warning` | `#92400E` | Verification / auth warning banners | Semantic warning (`#FFFBEB` bg) |
| `--status-danger` | `#B91C1C` | Inline validation alerts & failed states | Semantic error (`#FEF2F2` bg, `>= 6.1:1`) |
| Radii Scale | `full` / `xl` / `2xl` / `3xl` | Buttons (`rounded-full`), inputs (`rounded-xl`), cards (`rounded-2xl`), modals (`rounded-3xl`) | Unified soft-rounded silhouette |
| Focus Ring | `2px solid #15803D` (`outline-offset: 2px`) | Global `:focus-visible` ring | WCAG 2.2 Focus Appearance |
| Reduced Motion | `@media (prefers-reduced-motion: reduce)` | Collapses transitions/animations to `0.01ms` | Respects OS vestibular preference |
| Skip Link | `.skip-link` -> `#studio-main` | Pill bypass link revealed on `:focus` | Keyboard quick navigation |

### Typography & Multilingual Script Safety
- **UI Font:** `Inter`, system sans fallback.
- **Telemetry/Numbers:** `JetBrains Mono` with `tabular-nums`.
- **Urdu Nastaliq (`ur`):** `Noto Nastaliq Urdu` with `.font-script-ur { line-height: 1.9; }` and `rounded-full` highlight chips using `px-2.5 py-1 text-[11px] leading-relaxed` so tall Nastaliq ascenders/descenders never collide with pill edges.
- **Arabic (`ar`):** `Noto Sans Arabic`, `line-height: 1.5`.
- **Hindi (`hi`):** `Noto Sans Devanagari`, `line-height: 1.55`.

---

## 6. Component Inventory & All Required UI States

| Component | Loading | Empty | Error | Partial | Success / Active | Disabled |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **StudioWorkspace** | Auth-check skeleton | Unauthenticated amber banner | Top `aria-live="polite"` banner | Empty queue + loaded draft | Creamy canvas, `372px` + `flex-1` stage | Unauthenticated gating |
| **StudioHeader** | Spin/pulse credit pill | Single default workspace | Workspace error banner | Amber `Verify` pill | Active workspace, Credits pill, green `Buy Credits` pill | Disabled while syncing |
| **ProductScraperPanel** | Warm cream skeleton | Calm empty draft + green template pill | `onBlur` `<p role="alert">` + banner | Drawer collapsed/expanded | Green active script/format pills + Generate pill | Locked when unconfirmed or 0 credits |
| **RemotionPreviewStage** | Creamy-warm buffering box | Default localized preview loaded | Fallback image placeholder | Draft captions preview | Interactive Player + green `Download MP4` pill | Download hidden until complete |
| **RenderQueueGallery** | Warm card skeletons | Calm empty box + green CTA pill | `#FEF2F2` / `#B91C1C` `Failed · Refunded` + `Retry` | Active 4-step `#15803D` bar | Selected card `#15803D` border + `MP4` green pill | Action buttons scoped to state |
| **CreditCheckoutModal** | Skeleton ledger rows | Empty credit history card | Soft-red alert + `Retry` pill | Pending ledger rows | 3 white pack cards + green checkout pills + `overflow-x-auto` table | Prevent double checkout click |
| **AuthModal** | Submitting spinner | Clean form inputs | `onBlur` `<p role="alert">` + API error box | Verify email / reset flow | Green pill CTA & clean auto-dismiss | Disabled while submitting |

---

## 7. Responsive Screen Specs & Touch Targets

### Touch Target Baseline
- **Primary Pill CTAs & Form Inputs (`Generate`, `Fetch`, `Buy Credits`, Auth Submit, Empty State CTA):** `min-h-[40px]` to `min-h-[44px]`.
- **Secondary Pill Buttons, Filter Tabs & Modal Close Buttons:** `min-h-[32px]` to `min-h-[36px]`, meeting and exceeding WCAG 2.2 AA `24x24px` target guidelines.

### Breakpoints
1. **`1280px+` (Desktop):** Single-row sticky header (`<= 80px` height); `372px` `Create Video Ad` card beside `flex-1` `Live Preview` card with immediate above-the-fold player & Captions column; full-width 3-column `Recent Videos` gallery below.
2. **`768px` (Tablet):** Header wraps gracefully; studio cards stack `flex-col` cleanly without overlap; gallery shows `md:grid-cols-2`.
3. **`375px` & `320px` (Mobile):** Tight responsive gutters (`px-4 py-5`) and `min-w-0` flex/grid children; all `rounded-full` buttons, language pills, Remotion frame, and `CreditCheckoutModal` ledger (`overflow-x-auto`) stay strictly within `320px` (`scrollWidth <= innerWidth`).
