---
name: steplearn
mood: warm-neutral
accent: "#e07b4b"
font: ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif
radius: 8px
spacing: [4, 8, 12, 16, 20, 24, 32, 40, 48]
colors:
  surface:
    bg: "#f8f7f4"
    bg-alt: "#f1f0ec"
    card: "#ffffff"
  text:
    primary: "#1a1a1a"
    body: "#37352f"
    secondary: "#6b6b6b"
    mute: "#9b9b9b"
  accent:
    base: "#e07b4b"
    hover: "#d06a3a"
    light: "#fef3ed"
  semantic:
    success: "#0f7b4e"
    success-light: "#effaf3"
    danger: "#d93a46"
    danger-light: "#fef4f4"
    info: "#4b8dc7"
    info-light: "#eef5fb"
  border: "#e8e6e1"
shadows:
  sm: "0 1px 2px rgba(0,0,0,.03)"
  md: "0 1px 3px rgba(0,0,0,.06), 0 2px 8px rgba(0,0,0,.02)"
  lg: "0 4px 24px rgba(0,0,0,.08)"
type-scale:
  h1: "1.5rem / 700 / 1.3"
  h2: "1.15rem / 600 / 1.4"
  body: "0.875rem / 400 / 1.6"
  caption: "0.75rem / 400 / 1.5"
components:
  card:
    description: White card with soft shadow, no border. Rounded corners 10px.
    style: "background: var(--card); border-radius: 10px; padding: 20px; box-shadow: var(--shadow); border: none;"
  button-primary:
    description: Warm orange filled button with subtle hover lift.
    style: "background: var(--accent); color: #fff; border: none; border-radius: 8px; padding: 8px 20px; font-weight: 600; transition: all .15s; cursor: pointer;"
  button-primary-hover:
    style: "background: var(--accent-hover); transform: translateY(-1px); box-shadow: var(--shadow);"
  badge:
    description: Pill-shaped inline label for status.
    style: "display: inline-block; padding: 2px 10px; border-radius: 100px; font-size: .75rem; font-weight: 600;"
  modal-overlay:
    description: Blurred backdrop with fade-in animation.
    style: "background: rgba(0,0,0,.25); backdrop-filter: blur(4px); animation: fadeIn .2s ease;"
  modal:
    description: Card with scale-up enter animation.
    style: "background: var(--card); border-radius: 12px; padding: 28px; box-shadow: var(--shadow-lg); animation: modalEnter .25s ease;"
  input:
    description: Rounded input with focus ring.
    style: "border: 1px solid var(--border); border-radius: 8px; padding: 8px 12px; font-size: .875rem; transition: border-color .15s, box-shadow .15s;"
  input-focus:
    style: "border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-light); outline: none;"
  table:
    description: Clean table with subtle header background.
    style: "background: var(--card); border-radius: 10px; overflow: hidden; box-shadow: var(--shadow);"
  table-header:
    style: "background: var(--bg-alt); padding: 10px 14px; font-size: .8rem; font-weight: 600; color: var(--sub);"
  nav-tab:
    description: Underline-style tab for active state.
    style: "padding: 8px 16px; border: none; background: none; font-size: .875rem; color: var(--sub); cursor: pointer; border-bottom: 2px solid transparent; transition: all .15s;"
  nav-tab-active:
    style: "color: var(--accent); border-bottom-color: var(--accent); font-weight: 600;"
animations:
  fadeIn: "from { opacity: 0; } to { opacity: 1; }"
  modalEnter: "from { opacity: 0; transform: scale(.95) translateY(8px); } to { opacity: 1; transform: scale(1) translateY(0); }"
  spin: "to { transform: rotate(360deg); }"
---

# 拾阶而上 — Notion-Style Design System

## 1. Visual Theme & Atmosphere

A warm, clean, education-friendly interface inspired by Notion's minimalism. The palette is built around warm neutrals with a muted orange accent — approachable for parents, clear for teachers, and engaging for students.

**Mood keywords:** readable, calm, structured, friendly, focused.

**Density:** Medium — enough information density for admin work, but enough whitespace to feel open and not cramped.

## 2. Color Palette & Roles

| Token | Hex | Role |
|---|---|---|
| `--bg` | `#f8f7f4` | Page background — warm light gray |
| `--bg-alt` | `#f1f0ec` | Secondary surface — table headers, hover states, alternate rows |
| `--card` | `#ffffff` | Card / container surface |
| `--text` | `#1a1a1a` | Primary text — headings, body copy |
| `--text-alt` | `#37352f` | Body text — slightly softer than headings |
| `--sub` | `#6b6b6b` | Secondary / meta text |
| `--mute` | `#9b9b9b` | Placeholder / very weak text |
| `--accent` | `#e07b4b` | Primary brand — warm orange |
| `--accent-hover` | `#d06a3a` | Button hover / active state |
| `--accent-light` | `#fef3ed` | Light accent background |
| `--green` | `#0f7b4e` | Success — softer green |
| `--green-light` | `#effaf3` | Light success background |
| `--red` | `#d93a46` | Error / danger |
| `--red-light` | `#fef4f4` | Light danger background |
| `--blue` | `#4b8dc7` | Info |
| `--blue-light` | `#eef5fb` | Light info background |
| `--border` | `#e8e6e1` | Borders / dividers |

## 3. Typography Rules

**Font stack:** `ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif`

| Level | Size | Weight | Line-height | Usage |
|---|---|---|---|---|
| h1 / .page-title | 1.5rem | 700 | 1.3 | Page headings |
| h2 | 1.15rem | 600 | 1.4 | Section headings, card titles |
| body | 0.875rem | 400 | 1.6 | Paragraphs, form labels, table cells |
| caption | 0.75rem | 400 | 1.5 | Badges, meta text, timestamps |

- Headings use `--text` (`#1a1a1a`), body uses `--text-alt` (`#37352f`).
- Section headings use a left accent border: `border-left: 3px solid var(--accent); padding-left: 12px;`

## 4. Component Stylings

### Cards
- White surface, no border, layered shadows.
- `border-radius: 10px`, `padding: 20px`, `box-shadow: var(--shadow)`.
- Hover: subtle lift via `transform: translateY(-1px)` and `box-shadow: var(--shadow-lg)` on interactive cards.

### Buttons
- Primary: filled accent orange. Hover: darker orange + 1px lift.
- Secondary: outlined with `--border`. Hover: `--bg-alt` background.
- Small: `btn-sm` with `padding: 4px 12px; font-size: .8em`.
- All buttons: `transition: all .15s ease; min-height: 36px;`

### Tables
- Full-width, white background, 10px radius, shadow.
- Header: `--bg-alt` background, subtle text.
- Rows: bordered-bottom with `--border`.
- Tables wrapped in `overflow-x: auto` for mobile scroll.

### Forms
- Inputs: 8px radius, 1px border, focus ring (`box-shadow: 0 0 0 3px var(--accent-light)`).
- Labels: 0.8rem, 600 weight, `--sub` color above input.
- `.form-row`: 2-column grid, stacks to 1 column below 640px.

### Badges
- Pill shape (`border-radius: 100px`), compact padding, 600 weight.
- Color variants use corresponding `--*-light` backgrounds with `--*` text.

### Modals
- Overlay: `blur(4px)` backdrop, `fadeIn` animation.
- Content card: `modalEnter` animation (scale 0.95→1 + 8px upward slide).
- Max width 560px, 90% width on mobile.

## 5. Layout Principles

- **Page max-width:** 1200px for teacher app, 700px for student page.
- **Stats grid:** `repeat(auto-fit, minmax(160px, 1fr))` with 16px gap.
- **Section spacing:** 24px between sections.
- **Horizontal scroll wrapper** for all table containers on mobile.

## 6. Depth & Elevation

| Level | Token | Usage |
|---|---|---|
| 0 | none | Page background |
| 1 | `--shadow-sm` | Subtle separation (hover feedback) |
| 2 | `--shadow` | Cards, stat blocks, tables |
| 3 | `--shadow-lg` | Modals, dropdowns |

No borders for card elevation — use shadow only.

## 7. Responsive Behavior

- Breakpoint: `@media (max-width: 640px)` for single-column form stacking.
- Teacher nav: horizontal scroll overflow on mobile.
- Tables: `overflow-x: auto` wrapper on all tables.
- Touch targets: `min-height: 36px` for buttons, `min-width: 44px` for icon buttons.

## 8. Motion & Animation

| Element | Animation | Duration |
|---|---|---|
| Modal overlay | `fadeIn` opacity | 0.2s ease |
| Modal content | `modalEnter` scale+slide | 0.25s ease |
| Button hover | `translateY(-1px)` + shadow | 0.15s ease |
| Card hover | `translateY(-2px)` + shadow | 0.2s ease |
| Spinner | `spin` rotate infinite | 1s linear |

## 9. Do's and Don'ts

- ✅ Do: Use shadows for elevation, not borders.
- ✅ Do: Keep warm neutral palette — no pure black `#000` or stark white `#fff` for text/bg.
- ✅ Do: Use `--bg-alt` for table headers and alternate rows.
- ✅ Do: Wrap tables in `overflow-x: auto` for mobile.
- ❌ Don't: Use the old orange `#e8813b` — use `#e07b4b`.
- ❌ Don't: Add borders to cards — use `var(--shadow)`.
- ❌ Don't: Hardcode px values outside the spacing scale (4, 8, 12, 16, 20, 24, 32, 40, 48).
