---
name: bancoctt-design
description: Banco CTT's design system for web frontends - colour roles, Inter type styles, spacing, the phone/tablet/desktop layouts, component specs, light and dark themes, and the tokens.css file to import. Use this skill for any UI work on a Banco CTT product (home banking, the app's web screens, back-office tools, dashboards, prototypes) whenever the user mentions Banco CTT, bancoctt or CTT bank, or asks to build, style, theme or review pages, components, forms, tables or charts in Banco CTT's look, even if they never say "design system". Also use it to review existing Banco CTT UI code for hard-coded colours, invented components or missing dark mode.
---

# Banco CTT design system

Everything needed to build a Banco CTT web frontend: the full reference in `references/DESIGN.md`, the tokens as CSS in `assets/tokens.css`, the same tokens in DTCG JSON in `assets/design-tokens.dtcg.json`, and the logos in `assets/`.

## Set up the frontend (once per project)

1. Copy `assets/tokens.css` into the project and load it before any other stylesheet. Copy the logo files you need (`assets/bancoctt-logo.svg`, `assets/bancoctt-logo-dark.svg`). Don't edit the copies; when this skill changes, copy them again.
2. Load the Inter font, Regular 400 and Bold 700 (DESIGN.md › Typography).
3. Add the base styles from DESIGN.md › Implementation › Base styles.
4. Wire the Light / Dark / System switch as DESIGN.md › Colors › Switching themes describes, applied before first paint.

## Rules

Section names in parentheses below are sections of `references/DESIGN.md`.

Follow these rules exactly:

1. **Import `tokens.css` and use only its variables** for every colour, font size, space, radius and shadow. No hex, `rgb()` or named colours in component CSS or inline styles. The only exceptions are white `#FFFFFF` on `--primary` and the document-page white in Components.
2. **Use roles by meaning, not by look:**
   - action → `--primary`
   - selected or active → `--brand-text` / `--surface-active` / `--primary-tint`
   - link → `--link`
   - status → a container colour plus `--text`
   - categorical → `--cat-*` together with a text label
3. **Use one primary button per view.** Buttons are 48px-tall rectangles with a 4px radius and Bold 14px labels, at most 343px wide in forms, stacked 8px apart.
4. **Build inputs as filled fields with an underline** (Components), not outlined boxes.
5. **Build cards** as `--surface` + 10px radius + `--card-outline`, flat, on `--surface-page`. Add `--shadow` only to cards that carry their own action.
6. **Support both themes and System** (Colors › Switching themes), applied before first paint. Check every screen in both.
7. **Build the three layout bands** (Layout) and test at 375, 834 and 1440px at least. No horizontal scroll; grid columns use `minmax(0, 1fr)`.
8. **Respect the contrast rules** (Colors › Contrast, Accessibility). Don't use the light-theme failing roles for body-size text that must be read.
9. **Use Inter, with the styles in Typography only**: Regular 400 and Bold 700, with their line heights and letter spacing. Don't invent sizes or weights.
10. **Pick the closest component in Components** when unsure, and say so in the code comment. Don't create new colours.
    - Desktop navigation is the 200px side menu with icon and label; active items are red with no background.
    - Messages inside a page are feedback blocks; transient messages are the dark toast.
11. **Before handing over:** grep the CSS and JS for `#`, `rgb(` and `hsl(` outside `tokens.css` and justify every hit.

## Where to look in references/DESIGN.md

The file is about 900 lines. Its first ~265 lines are a YAML header holding every token value; skip it unless you need a raw value. Find the heading you need and read that section only:

| You are building or checking | Read |
|---|---|
| Any colour choice, theme switching, chart colours | `## Colors` (Role values, Switching themes, Categorical palette, Contrast) |
| Text styles | `## Typography` |
| Page structure, side menu, top bar, phone bottom bar, tablet, breakpoints | `## Layout` |
| Shadows and dark-theme outlines | `## Elevation & Depth` |
| Radii, borders, focus ring | `## Shapes` |
| A specific component (buttons, inputs, tabs, lists, cards, modal, toast, table, …) | `## Components`, then its `###` heading |
| A quick sanity check of a finished screen | `## Do's and Don'ts` |
| Copy language, numbers, motion | `## Content, imagery, motion` |
| Keyboard, focus, touch targets | `## Accessibility` |
| The token file, logos, base styles | `## Implementation` |
| Why something looks unfinished in Banco CTT's sources | `## Known issues` |

## Where the specs come from

Every spec in DESIGN.md is marked **(Figma)** (Banco CTT's real screens), **(tokens)** (Banco CTT's token export) or **(ours)** (defined by this design system where Banco CTT has nothing). The dark theme, the tablet layouts and data tables are **(ours)**. Several light-theme colours from Banco CTT fail contrast for body text; they are kept as specified, so follow the usage rule in Colors › Contrast rather than swapping colours. Using the logo in a product needs Banco CTT's permission.
