---
version: alpha
name: Banco CTT Design System
description: "Reference for building any Banco CTT web frontend. Light theme from Banco CTT's real screens (Figma) and token export; dark theme, tablet layouts and data tables defined here. Every colour role has a light value (`role`) and a dark value (`role-dark`); tokens.css switches between them."
colors:
  # constant in both themes
  primary: "#E00024"
  primary-active: "#C4001F"
  text-on-primary: "#FFFFFF"
  success: "#00BFB4"
  alert: "#FFC800"
  offline: "#A681AB"
  highlight: "#B5CB32"
  # roles: light theme
  surface-page: "#F7F9FC"
  surface: "#FFFFFF"
  surface-raised: "#FFFFFF"
  surface-bar: "#F1F4F8"
  surface-overlay: "#F7F9FC"
  surface-field: "#F1F4F8"
  surface-field-hover: "#F7F9FC"
  surface-hover: "#F7F9FC"
  surface-active: "#F1F4F8"
  surface-inverse: "#333333"
  divider: "#E4E9F2"
  control-border: "#C5CEE0"
  card-outline: "transparent"
  field-line: "#CCCCCC"
  field-line-filled: "#666666"
  field-line-selected: "#000000"
  text: "#000000"
  text-strong: "#000000"
  text-title: "#333333"
  text-weak: "#666666"
  text-section: "#999999"
  text-disabled: "#CCCCCC"
  text-secondary: "#8F9BB3"
  text-on-inverse: "#FFFFFF"
  brand-text: "#E00024"
  brand-text-on-tint: "#C4001F"
  link: "#00BFB4"
  error-text: "#EC677D"
  alert-text: "#CC9500"
  primary-hover: "#EC677D"
  primary-disabled: "#FBDFE3"
  primary-tint: "#FBDFE3"
  container-primary: "#FBDFE3"
  container-info: "#E3F0F0"
  container-alert: "#FFF1BF"
  container-offline: "#F1EAF1"
  container-highlight: "#F0F0E3"
  chip-fixed: "#6E7B93"
  chip-fluid: "#E4E9F2"
  overlay: "rgba(51, 51, 51, 0.6)"
  skeleton: "#EBEBEB"
  cat-0: "#E00024"
  cat-1: "#00BFB4"
  cat-2: "#A681AB"
  cat-3: "#CC9500"
  cat-4: "#6E7B93"
  cat-5: "#A4BF00"
  cat-6: "#EC677D"
  cat-7: "#68396F"
  # roles: dark theme (same role names with -dark)
  surface-page-dark: "#12151B"
  surface-dark: "#1A1E26"
  surface-raised-dark: "#232833"
  surface-bar-dark: "#171B22"
  surface-overlay-dark: "#171B22"
  surface-field-dark: "#242A35"
  surface-field-hover-dark: "#2A303C"
  surface-hover-dark: "#232833"
  surface-active-dark: "#262B35"
  surface-inverse-dark: "#F1F4F8"
  divider-dark: "#2C3340"
  control-border-dark: "#8F9BB3"
  card-outline-dark: "#2C3340"
  field-line-dark: "#6E7B93"
  field-line-filled-dark: "#C5CEE0"
  field-line-selected-dark: "#F1F4F8"
  text-dark: "#F1F4F8"
  text-strong-dark: "#FFFFFF"
  text-title-dark: "#F1F4F8"
  text-weak-dark: "#C5CEE0"
  text-section-dark: "#8F9BB3"
  text-disabled-dark: "#5C6578"
  text-secondary-dark: "#A9B4C9"
  text-on-inverse-dark: "#12151B"
  brand-text-dark: "#EC677D"
  brand-text-on-tint-dark: "#EC677D"
  link-dark: "#66D8D3"
  error-text-dark: "#FFA3B0"
  alert-text-dark: "#FFC800"
  primary-hover-dark: "#C4001F"
  primary-disabled-dark: "#4A1520"
  primary-tint-dark: "#3A1520"
  container-primary-dark: "#4A1520"
  container-info-dark: "#0F3B39"
  container-alert-dark: "#3D3200"
  container-offline-dark: "#35213A"
  container-highlight-dark: "#2E3410"
  chip-fixed-dark: "#C5CEE0"
  chip-fluid-dark: "#2C3340"
  overlay-dark: "rgba(0, 0, 0, 0.6)"
  skeleton-dark: "#232833"
  cat-0-dark: "#EC677D"
  cat-1-dark: "#33CBC4"
  cat-2-dark: "#C8B1CB"
  cat-3-dark: "#FFC800"
  cat-4-dark: "#C5CEE0"
  cat-5-dark: "#B5CB32"
  cat-6-dark: "#FFA3B0"
  cat-7-dark: "#A681AB"
typography:
  h4:
    fontFamily: Inter
    fontSize: 34px
    fontWeight: 700
    lineHeight: "1.1206"
    letterSpacing: 0.25px
  h5:
    fontFamily: Inter
    fontSize: 24px
    fontWeight: 700
    lineHeight: "1.2"
    letterSpacing: 0px
  h6:
    fontFamily: Inter
    fontSize: 20px
    fontWeight: 700
    lineHeight: "1.12"
    letterSpacing: 0.15px
  paragraph-1:
    fontFamily: Inter
    fontSize: 16px
    fontWeight: 400
    lineHeight: "1.5"
    letterSpacing: 0.44px
  paragraph-2:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: 400
    lineHeight: "1.4286"
    letterSpacing: 0.25px
  subtitle-2:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: 700
    lineHeight: "1.1429"
    letterSpacing: 0.1px
  button:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: 700
    lineHeight: "1.75"
    letterSpacing: 0px
  caption:
    fontFamily: Inter
    fontSize: 12px
    fontWeight: 400
    lineHeight: "1.3333"
    letterSpacing: 0.4px
  input-label:
    fontFamily: Inter
    fontSize: 12px
    fontWeight: 400
    letterSpacing: 0.11px
  badge:
    fontFamily: Inter
    fontSize: 12px
    fontWeight: 700
    lineHeight: "1.1667"
    letterSpacing: 0.29px
  navbar:
    fontFamily: Inter
    fontSize: 10px
    fontWeight: 700
    lineHeight: "1.6"
    letterSpacing: 0.33px
rounded:
  sm: 4px
  md: 6px
  lg: 8px
  xl: 10px
  2xl: 40px
  full: 999px
spacing:
  space-1: 4px
  space-2: 8px
  space-3: 12px
  space-4: 16px
  space-6: 24px
  space-8: 32px
  space-10: 40px
  space-12: 48px
  menu-width: 200px
  menu-width-collapsed: 72px
  topbar-height: 72px
  content-width: 968px
  column-gap: 32px
  control-height: 48px
  button-max-width: 343px
  list-item-min-height: 64px
  modal-width: 568px
  icon: 24px
  icon-inline: 16px
  breakpoint-phone: 375px
  breakpoint-tablet: 834px
  breakpoint-tablet-landscape: 1112px
  breakpoint-desktop: 1280px
  breakpoint-desktop-design: 1440px
components:
  button-primary: { backgroundColor: "{colors.primary}", textColor: "{colors.text-on-primary}", typography: "{typography.button}", rounded: "{rounded.sm}", padding: 12px, height: 48px, width: 343px }
  button-primary-hover: { backgroundColor: "{colors.primary-hover}", textColor: "{colors.text-on-primary}" }
  button-primary-active: { backgroundColor: "{colors.primary-active}", textColor: "{colors.text-on-primary}" }
  button-primary-disabled: { backgroundColor: "{colors.primary-disabled}", textColor: "{colors.text-on-primary}" }
  button-secondary: { backgroundColor: "{colors.surface}", textColor: "{colors.brand-text}", typography: "{typography.button}", rounded: "{rounded.sm}", padding: 12px, height: 48px, width: 343px }
  button-secondary-hover: { backgroundColor: "{colors.surface-active}", textColor: "{colors.brand-text}" }
  button-secondary-active: { backgroundColor: "{colors.primary-tint}", textColor: "{colors.brand-text-on-tint}" }
  button-icon: { textColor: "{colors.text}", size: 24px }
  input: { backgroundColor: "{colors.surface-field}", textColor: "{colors.text}", typography: "{typography.paragraph-2}", rounded: "{rounded.sm}", padding: 12px, height: 48px }
  input-label: { backgroundColor: "{colors.surface-field}", textColor: "{colors.text-weak}", typography: "{typography.input-label}" }
  input-hover: { backgroundColor: "{colors.surface-field-hover}", textColor: "{colors.text}" }
  radio: { backgroundColor: "{colors.surface-field}", size: 20px, rounded: "{rounded.full}" }
  checkbox: { backgroundColor: "{colors.surface-field}", size: 20px, rounded: "{rounded.sm}" }
  checkbox-checked: { backgroundColor: "{colors.primary}", textColor: "{colors.text-on-primary}" }
  toggle: { backgroundColor: "{colors.surface-field}", width: 52px, height: 32px, rounded: "{rounded.full}" }
  toggle-on: { backgroundColor: "{colors.primary}", textColor: "{colors.text-on-primary}" }
  tab: { backgroundColor: "{colors.surface-page}", textColor: "{colors.text-secondary}", typography: "{typography.subtitle-2}" }
  tab-active: { backgroundColor: "{colors.surface-page}", textColor: "{colors.brand-text}" }
  list-item: { backgroundColor: "{colors.surface}", textColor: "{colors.text}", typography: "{typography.subtitle-2}", padding: 16px, height: 64px }
  list-item-caption: { backgroundColor: "{colors.surface}", textColor: "{colors.text-weak}", typography: "{typography.caption}" }
  list-item-hover: { backgroundColor: "{colors.surface-hover}", textColor: "{colors.text}" }
  list-item-selected: { backgroundColor: "{colors.surface-active}", textColor: "{colors.text}" }
  section-title: { backgroundColor: "{colors.surface-page}", textColor: "{colors.text-section}", typography: "{typography.subtitle-2}" }
  card: { backgroundColor: "{colors.surface}", textColor: "{colors.text}", rounded: "{rounded.xl}", padding: 16px }
  quick-action: { backgroundColor: "{colors.surface}", textColor: "{colors.text}", typography: "{typography.paragraph-2}", rounded: "{rounded.xl}", width: 145px, height: 112px }
  quick-action-badge: { backgroundColor: "{colors.primary}", textColor: "{colors.text-on-primary}", rounded: "{rounded.xl}", size: 40px }
  feedback-info: { backgroundColor: "{colors.container-info}", textColor: "{colors.text-title}", typography: "{typography.paragraph-2}", rounded: "{rounded.xl}", padding: 16px }
  feedback-alert: { backgroundColor: "{colors.container-alert}", textColor: "{colors.text-title}", rounded: "{rounded.xl}", padding: 16px }
  feedback-error: { backgroundColor: "{colors.container-primary}", textColor: "{colors.text-title}", rounded: "{rounded.xl}", padding: 16px }
  toast: { backgroundColor: "{colors.surface-inverse}", textColor: "{colors.text-on-inverse}", typography: "{typography.paragraph-2}", rounded: "{rounded.sm}", padding: 12px, width: 343px }
  modal: { backgroundColor: "{colors.surface-overlay}", textColor: "{colors.text-title}", typography: "{typography.subtitle-2}", rounded: "{rounded.xl}", width: 568px }
  progress-bar: { backgroundColor: "{colors.skeleton}", height: 12px, rounded: "{rounded.full}" }
  avatar: { backgroundColor: "{colors.container-primary}", textColor: "{colors.text}", typography: "{typography.subtitle-2}", size: 40px, rounded: "{rounded.full}" }
  chip-selected: { backgroundColor: "{colors.chip-fixed}", textColor: "{colors.text-on-inverse}", typography: "{typography.caption}", rounded: "{rounded.full}", height: 32px }
  chip-fluid: { backgroundColor: "{colors.chip-fluid}", textColor: "{colors.text}", typography: "{typography.caption}", rounded: "{rounded.full}" }
  citation-pill: { backgroundColor: "{colors.primary-tint}", textColor: "{colors.brand-text-on-tint}", typography: "{typography.badge}", rounded: "{rounded.full}", height: 20px }
  table-header: { backgroundColor: "{colors.surface}", textColor: "{colors.text-section}", typography: "{typography.subtitle-2}", padding: 16px, height: 48px }
  table-row: { backgroundColor: "{colors.surface}", textColor: "{colors.text}", typography: "{typography.paragraph-2}", padding: 16px, height: 48px }
  side-menu: { backgroundColor: "{colors.surface}", textColor: "{colors.text}", typography: "{typography.paragraph-2}", width: 200px }
  side-menu-item: { backgroundColor: "{colors.surface}", textColor: "{colors.text}", rounded: "{rounded.xl}", height: 48px }
  side-menu-item-active: { backgroundColor: "{colors.surface}", textColor: "{colors.brand-text}" }
  side-menu-section-title: { backgroundColor: "{colors.surface}", textColor: "{colors.text-section}", typography: "{typography.caption}" }
  top-bar: { backgroundColor: "{colors.surface-bar}", textColor: "{colors.text}", typography: "{typography.subtitle-2}", height: 72px, padding: 12px }
  bottom-navbar: { backgroundColor: "{colors.surface}", textColor: "{colors.text-secondary}", typography: "{typography.navbar}", rounded: "{rounded.xl}" }
  bottom-navbar-active: { backgroundColor: "{colors.surface}", textColor: "{colors.brand-text}" }
  status-success: { backgroundColor: "{colors.container-info}", textColor: "{colors.text}" }
  status-offline: { backgroundColor: "{colors.container-offline}", textColor: "{colors.text}" }
  status-highlight: { backgroundColor: "{colors.container-highlight}", textColor: "{colors.text}" }
  dark-surface: { backgroundColor: "{colors.surface-dark}", textColor: "{colors.text-dark}" }
  dark-surface-weak: { backgroundColor: "{colors.surface-dark}", textColor: "{colors.text-weak-dark}" }
  dark-button-secondary: { backgroundColor: "{colors.surface-dark}", textColor: "{colors.brand-text-dark}" }
  dark-input: { backgroundColor: "{colors.surface-field-dark}", textColor: "{colors.text-dark}" }
  dark-toast: { backgroundColor: "{colors.surface-inverse-dark}", textColor: "{colors.text-on-inverse-dark}" }
  dark-top-bar: { backgroundColor: "{colors.surface-bar-dark}", textColor: "{colors.text-dark}" }
---

# Banco CTT Design System

This is the reference for building any Banco CTT web frontend, by hand or with an agent. It's self-contained: the token values, component rules and layout patterns are all here. The same values are in the skill's `assets/tokens.css`, ready to import. Paths in this document are relative to the skill root (`bancoctt-design/`).

**Agents:** read "Instructions for agents" before writing code.

## Overview

A bright, calm banking UI.
- **Surfaces:** white cards sit on a very pale blue-grey page (`#F7F9FC`). Most cards are flat; cards that carry an action get a soft blue-grey shadow. Dividers are a faint blue-grey line.
- **Colour:** one brand red (`#E00024`) carries actions, selection and the active state of navigation. The cool **grey-blue** family is the secondary colour: inactive tabs and nav labels, chips, help text and the page tint. Teal (blue-green) means success and info, yellow means alert or pending, purple means offline, and lime is a highlight.
- **Type:** **Inter**, in two weights. Titles, list titles, tabs and buttons are **Bold (700)**; everything else is Regular (400), with slightly open letter spacing.
- **Buttons** are rectangles with 4px corners, 48px tall. Primary is solid red; secondary is a red outline.
- **Form fields** are *filled*: a pale blue-grey box with an underline, and the label sits inside the box above the value.
- **Desktop navigation** is a white 200px side menu with icon and label, grouped under grey section titles. On phones it's a bottom bar.

**Personality:** a modern digital bank. Clean, quiet, trustworthy, with red used sparingly as the signal.

**Provenance.** Three sources, in order of authority:
1. **Banco CTT's real screens** in Figma (file `KT4rQSWoBxvuOCBHyWLm76`, page "TO BE // v3": 20 home-banking screens at 1440px and 19 app screens at 375px). Component sizes, radii, type styles and layout come from the Figma variables and generated code of these screens, read directly through the Figma API on 2026-10-03. Marked **(Figma)** below.
2. **Banco CTT's token export** (`source/figma-tokens/*.tokens.json` in the design-system repository, not shipped in the skill): colour scales, roles and per-component colour states, including hover, pressed and disabled states the screens don't show. Marked **(tokens)**.
3. **This document's own design**, where Banco CTT has nothing. Marked **(ours)**:
   - the dark theme (Colors)
   - the tablet layouts (Layout)
   - data tables (Components)
   - every component state or size the screens and tokens don't show

No Banco CTT component library was available. The component specs in Components are derived from how the components appear in the real screens, so states that don't appear there (focus, hover on some components, error on inputs) are ours or come from the token export, as marked.

## Colors

### Rule: always use roles

Backgrounds, text, lines and feedback colours are **semantic roles** whose values flip between themes. Product code uses role variables (`var(--surface)`, `var(--text)`, …) and never hex values.
- **Constant in both themes:** the primary red `#E00024`, its pressed state `#C4001F`, and white on primary.
- **The accent hues stay the same family** (success teal, alert yellow, offline purple, highlight lime), but the step used for text and containers changes per theme.

### Role values

| Role | Light (source token) | Dark (proposal) | Use |
|---|---|---|---|
| `--surface-page` | `#F7F9FC` (bg-page-default) | `#12151B` | Page background |
| `--surface` | `#FFFFFF` (bg-container-neutral0) | `#1A1E26` | Cards, panels, app bar, drawers, bottom navbar |
| `--surface-raised` | `#FFFFFF` | `#232833` | Menus, popovers, the expanded tablet menu |
| `--surface-bar` | `#F1F4F8` (topnavbar-bg, Figma) | `#171B22` | Top bar |
| `--surface-overlay` | `#F7F9FC` (drawer-bg2, Figma) | `#171B22` | Modal and drawer panels (cards inside them are `--surface`) |
| `--surface-field` | `#F1F4F8` (forms-input-bg-default) | `#242A35` | Filled inputs, unchecked controls, toggle track, segmented controls |
| `--surface-field-hover` | `#F7F9FC` (forms-input-bg-hover) | `#2A303C` | Input hover |
| `--surface-hover` | `#F7F9FC` (lists-bg-hover) | `#232833` | List-item and icon-button hover |
| `--surface-active` | `#F1F4F8` (lists-bg-active) | `#262B35` | Selected list item; secondary/ghost button hover |
| `--surface-inverse` | `#333333` (toast-bg, Figma) | `#F1F4F8` | Toast; inverse containers such as tooltips and the user's own chat bubble |
| `--divider` | `#E4E9F2` (divider-default) | `#2C3340` | Dividers, panel borders |
| `--control-border` | `#C5CEE0` (controls-listitems-border-default) | `#8F9BB3` | Checkbox, radio and toggle outlines |
| `--card-outline` | `transparent` | `#2C3340` | Card and bar outline (dark relies on it instead of shadow) |
| `--field-line` | `#CCCCCC` (forms-input-divider-default) | `#6E7B93` | Input underline, empty |
| `--field-line-filled` | `#666666` | `#C5CEE0` | Input underline, filled |
| `--field-line-selected` | `#000000` | `#F1F4F8` | Input underline, focused |
| `--text` | `#000000` (text-default) | `#F1F4F8` | Body text, headings, labels |
| `--text-strong` | `#000000` | `#FFFFFF` | Maximum emphasis |
| `--text-title` | `#333333` (header-text-title, Figma) | `#F1F4F8` | Page and modal titles, feedback-block text |
| `--text-weak` | `#666666` (text-color-neutral400) | `#C5CEE0` | Field labels, placeholders, assistive text, descriptions |
| `--text-section` | `#999999` (text-sectiontitle) | `#8F9BB3` | Section titles (group labels above lists) |
| `--text-disabled` | `#CCCCCC` | `#5C6578` | Disabled text |
| `--text-secondary` | `#8F9BB3` (secondary-500) | `#A9B4C9` | Inactive tabs and nav labels, metadata, timestamps |
| `--text-on-inverse` | `#FFFFFF` | `#12151B` | Text on `--surface-inverse` and on the selected fixed chip |
| `--brand-text` | `#E00024` | `#EC677D` | Red text: secondary/ghost buttons, active tab, active menu item, selected list item |
| `--brand-text-on-tint` | `#C4001F` | `#EC677D` | Red text on `--primary-tint` (citation pills, badges on pink) |
| `--link` | `#00BFB4` (text-link) | `#66D8D3` | Links |
| `--error-text` | `#EC677D` (assistive error) | `#FFA3B0` | Field error messages |
| `--alert-text` | `#CC9500` (text-alert&pending) | `#FFC800` | Pending and alert text |
| `--primary-hover` | `#EC677D` (button-primary-bg-hover) | `#C4001F` | Primary button hover |
| `--primary-disabled` | `#FBDFE3` | `#4A1520` | Disabled primary button |
| `--primary-tint` | `#FBDFE3` (bg-container-primary) | `#3A1520` | Pressed secondary/ghost, active icon button, active side-menu item, citation pills |
| `--container-primary` | `#FBDFE3` | `#4A1520` | Red-tinted container (error banner, avatar) |
| `--container-info` | `#E3F0F0` (bg-container-info) | `#0F3B39` | Info and success banners |
| `--container-alert` | `#FFF1BF` (bg-container-alert) | `#3D3200` | Alert and pending banners and tags |
| `--container-offline` | `#F1EAF1` (offline-100) | `#35213A` | Offline state |
| `--container-highlight` | `#F0F0E3` (highlight-100) | `#2E3410` | Highlight and "new" |
| `--chip-fixed` | `#6E7B93` (chips-fixed-default) | `#C5CEE0` | Fixed chip: selected fill, unselected text and outline; segmented-control selection |
| `--chip-fluid` | `#E4E9F2` (chips-fluid-default) | `#2C3340` | Fluid (filter/input) chips, file-type badges |
| `--overlay` | `#333333` at 60% | `#000000` at 60% | Modal and drawer scrim |
| `--skeleton` | `#EBEBEB` (skeleton-default) | `#232833` | Loading placeholders |
| `--shadow` | `0 5px 6px rgba(197,206,224,.5)` | `none` (`--card-outline` instead) | Cards, app bar, sticky bars |
| `--shadow-float` | `0 0 6px rgba(197,206,224,.5)` | `0 4px 16px rgba(0,0,0,.6)` | Floating buttons, menus, overlays, bottom navbar |

How the dark values were derived:
- **Surfaces** are blue-tinted near-blacks, matching the grey-blue secondary. They get lighter as they come forward: page → card → raised.
- **Text** is grey-blue-200 (`#F1F4F8`), not pure white. Weak text is grey-blue-400.
- **Red text** uses red-300 and errors red-200, so they stay readable on dark. The primary *fill* stays `#E00024`. Its hover goes **darker** (red-600) because a lighter red fails with white text.
- **Containers** are deep tints of their hue, carrying `--text`.

### Switching themes

- Set `data-theme="light"` or `"dark"` on `<html>`. With no attribute, follow `prefers-color-scheme`. `tokens.css` does this.
- Offer **Light / Dark / System**. Store an explicit choice; *System* removes the attribute.
- Apply the stored choice **before first paint** with an inline script in `<head>`, or the page flashes the wrong theme.

### Primitive scales (both themes)

| Scale (semantic name) | 100 | 200 | 300 | 400 | 500 | 600 |
|---|---|---|---|---|---|---|
| Red (primary) | `#FBDFE3` | `#FFA3B0` | `#EC677D` | `#E63350` | `#E00024` | `#C4001F` |
| Grey-blue (secondary) | `#F7F9FC` | `#F1F4F8` | `#E4E9F2` | `#C5CEE0` | `#8F9BB3` | `#6E7B93` |
| Blue-green (success) | `#E3F0F0` | `#CCF2F0` | `#99E5E1` | `#66D8D3` | `#33CBC4` | `#00BFB4` |
| Yellow (alert) | `#FFF1BF` | `#FFE37F` | `#FFD84C` | `#FFC800` | `#CC9500` | `#997000` |
| Purple (offline) | `#F1EAF1` | `#EBE0EB` | `#DEC8DE` | `#C8B1CB` | `#A681AB` | `#68396F` |
| Lime (highlight) | `#F0F0E3` | `#E9EECB` | `#DAE39E` | `#C9D86D` | `#B5CB32` | `#A4BF00` |
| Neutral | `#EBEBEB` | `#CCCCCC` | `#999999` | `#666666` | `#333333` | `#000000` (0 = `#FFFFFF`) |

Alpha primitives: red-500 at 12%, neutral-500 at 60% (overlay), grey-blue-400 at 50% and 60% (shadows).
Gradients: **stepper** is red-100 → red-500 (vertical, red from 20%); **area chart** is grey-blue-400 → transparent.
Use primitives only to define roles, never directly in components.

### Categorical palette (charts, series, people, tags)

Eight hues, all from the scales above, with **one palette per theme** (`--cat-0` … `--cat-7`):

| | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 |
|---|---|---|---|---|---|---|---|---|
| Light | `#E00024` | `#00BFB4` | `#A681AB` | `#CC9500` | `#6E7B93` | `#A4BF00` | `#EC677D` | `#68396F` |
| Dark | `#EC677D` | `#33CBC4` | `#C8B1CB` | `#FFC800` | `#C5CEE0` | `#B5CB32` | `#FFA3B0` | `#A681AB` |

In the real screens, category badges and progress bars use red-300 `#EC677D`, blue-green-500 `#33CBC4`, grey-blue-600 `#6E7B93`, purple-500 `#A681AB` and lime-500 `#B5CB32` **(Figma)**. The palette above is ours: the same hues at steps that keep the most contrast.

**Rule:** a categorical colour **marks** an item (dot, bar, line, left border, chart series) and is never the only thing that identifies it. A text label always carries the name, in `--text`. Three light hues are below 3:1 on white (teal 2.30, yellow 2.67, lime 2.09) and light red is only 3.09, so they can't carry meaning on their own and must never be used as text colour. In dark, all eight are at least 5:1 on `--surface`.

### Contrast (WCAG 2.x, computed)

| Pair | Light | Dark | Verdict |
|---|---|---|---|
| `--text` on `--surface` | 21.00 | 15.14 | Pass AAA |
| `--text` on `--surface-field` | 19.04 | 13.06 | Pass AAA |
| `--text-weak` (labels) on `--surface-field` | 5.20 | 9.11 | Pass AA |
| `--text-secondary` on `--surface` | **2.80** | 8.00 | **Light fails** |
| White on primary `#E00024` | 5.01 | 5.01 | Pass AA |
| White on primary active `#C4001F` | 6.24 | 6.24 | Pass AA |
| `--brand-text` on `--surface` | 5.01 | 5.41 | Pass AA |
| `--brand-text` on `--surface-active` (secondary/ghost hover) | 4.54 | 4.60 | Pass AA |
| `--brand-text-on-tint` on `--primary-tint` (pills) | 4.98 | 5.20 | Pass AA |
| `--text` on containers | 16.77 – 18.59 | 11.16 – 13.41 | Pass AAA |
| `--text-on-inverse` on `--chip-fixed` (selected chip) | 4.27 | 11.56 | Light just below AA |
| **White on `--primary-hover`** | **3.09** (`#EC677D`) | 6.24 | **Light fails**: large text only |
| **`--link` on `--surface`** | **2.30** (`#00BFB4`) | 9.80 | **Light fails** |
| **`--text-section` on `--surface`** | **2.85** (`#999`) | 5.97 | **Light fails** |
| **`--error-text` on `--surface`** | **3.09** (`#EC677D`) | 8.84 | **Light fails** |
| **`--alert-text` on `--surface`** | **2.67** (`#CC9500`) | 10.75 | **Light fails** |
| **`--field-line` vs `--surface-field` (non-text)** | **1.46** | 3.37 | **Light below 3:1** |
| **`--control-border` vs `--surface` (non-text)** | **1.58** | 5.97 | **Light below 3:1** |
| Primary fill vs `--surface` (non-text) | 5.01 | 3.34 | Pass (≥ 3) |
| `--text-title` on `--surface-page` | 11.98 | 16.57 | Pass AAA |
| `--text` on `--surface-bar` | 19.04 | 15.65 | Pass AAA |
| Toast text on `--surface-inverse` | 12.63 | 16.57 | Pass AAA |
| Feedback-block text on its container | 10.09 – 11.18 | 11.16 – 13.41 | Pass AAA |
| **Back link (`--text-section`) on `--surface-page`** | **2.70** | 6.17 | **Light fails** |
| White on `--primary-disabled` (disabled button) | 1.25 | – | Exempt (disabled) |
| `--text-disabled` on `--surface` | 1.61 | 2.85 | Exempt (disabled) |

**The light-theme failures come from Banco CTT's source tokens.** This system keeps them as specified until the brand team decides. These replacements from Banco CTT's own scales pass, but aren't in the source:

| Failing role | Replacement | Contrast | Note |
|---|---|---|---|
| Primary hover | red-600 `#C4001F` | 6.24 | |
| Section titles | neutral-400 `#666666` | 5.74 | |
| Inactive tabs | grey-blue-600 `#6E7B93` | 4.27 | Large or Bold text only |
| Error text | red-600 `#C4001F` | 6.24 | |
| Alert text | yellow-600 `#997000` | 4.49 | Just below AA: large or Bold only |
| Links | darker teal `#007A73` | 5.21 | *Not on the scale*: needs brand approval |
| Input underline (empty) | neutral-300 `#999999` | 2.58 | Still below 3:1: needs a decision |

**Until replaced, in the light theme:** never use `--link`, `--error-text`, `--alert-text` or `--text-section` for text that must be read (body-size messages). Pair them with an icon or label in `--text`, or put them on the matching container.

## Typography

The family is **Inter**, in **Regular 400** and **Bold 700**, with fallback `system-ui, sans-serif`. Self-host the variable font (`InterVariable`, `font-weight: 100 900`) or load it from a font service.

These are the styles used in Banco CTT's real screens **(Figma)**:

| Style | Size / line height | Weight | Letter spacing | Use |
|---|---|---|---|---|
| H4 | 34 / 38.1px | Bold | 0.25px | Amounts and key figures (the decimals drop to H6) |
| H5 | 24 / 28.8px* | Bold | 0 | Centred page title on landing pages |
| H6 | 20 / 22.4px | Bold | 0.15px | Page title (`--text-title`), card titles |
| Paragraph 1 | 16 / 24px | Regular | 0.44px | Lead text, the "back" link |
| Paragraph 2 | 14 / 20px | Regular | 0.25px | Default UI text: menu items, list values, descriptions, toast, input value |
| Subtitle 2 | 14 / 16px | Bold | 0.1px | List-item titles, tabs, section titles, modal title, user name |
| Button | 14 / 24.5px | Bold | 0 | Button labels |
| Caption | 12 / 16px | Regular | 0.4px | List subtitles, field captions, menu section titles, metadata |
| Input label | 12px, normal | Regular | 0.11px | The label inside a filled field |
| Badge | 12 / 14px | Bold | 0.29px | Percentages, counters, category badges |
| Navbar | 10 / 16px | Bold | 0.33px | Phone bottom-bar labels |

\*H5's line height is exported as 100%; 28.8px (1.2) is ours.

Guidance:
- Weight separates **titles and actions** (Bold) from **content** (Regular). There is no Medium or Semi Bold.
- **Section titles** above lists and cards are Subtitle 2 in `--text-section`. Menu section titles are Caption in `--text-section`.
- **The default text size is 14px** (Paragraph 2). Use Paragraph 1 for lead text only.
- In phone inputs use at least 16px for the typed value, to stop iOS zooming (ours; the screens show 14px in a select).

**The token export defines a different, newer scale** (`novos-*`, "new"): Semi Bold 600 headings at 48/30/24/20/18/14, labels at 16/14/12, body 16/14, caption 12, with no line heights. None of the real screens use it. This document follows the screens. If Banco CTT confirms the new scale is the current one, swap the weights (700 → 600) and sizes in `tokens.css`; nothing else changes.

## Layout

**Spacing** (4px grid): 4 · 8 · 12 · 16 · 24 · 32 · 40 · 48. Values seen in the screens **(Figma)**:
- 4 between a title and its caption
- 8 between stacked buttons, and between a section title and its card
- 12 between an icon and its text
- 16 as card and list-item padding
- 24 between groups
- 32 between columns and between the page header and the content
- 40 as padding in a feature card

### Desktop: home banking (Figma, 1440px)

| Part | Spec |
|---|---|
| Side menu | 200px wide, full height, `--surface`. Padding 26px top, 16px sides. Logo 83 × 18px at the top, then 30px gap. Sections are 16px apart; each has a Caption title in `--text-section` and its items 8px below. |
| Menu item | 48px tall, 10px radius, padding 7 × 11px, 24px icon, 12px gap, Paragraph 2 label. Inactive: `--text` icon and label. **Active: `--brand-text` label and red icon, with no background.** |
| Collapse button | 32px circle on the menu's right edge (half outside), 56px from the top: `--surface`, 1px `--divider` border, soft shadow. It collapses the menu to icons only. |
| Top bar | 72px tall, `--surface-bar` (`#F1F4F8`), no shadow, padding 12 × 24px. Content is right-aligned: 24px avatar + user name (Subtitle 2) + 24px chevron, 8px apart. |
| Page | `--surface-page`. Content column is **968px** wide, centred in the space right of the menu, starting 120px from the top (48px below the top bar), with 48px bottom padding. |
| Page header | H6 title in `--text-title`, then 7px below it a back link: 24px arrow + "Voltar" in Paragraph 1 `--text-section`, 8px apart. 32px to the content. |
| Columns | Two columns of 468px with a 32px gap. Forms and action stacks are at most 343px wide inside a column. |

### Phone: app (Figma, 375px)

| Part | Spec |
|---|---|
| Page | `--surface-page`, 16px side padding. Cards are full width (343px). |
| Header | 74px: padding 25px top, 15px bottom, 16px sides. Either a left-aligned H6 title, or a 24px back/close icon + centred Subtitle 2 title (+ optional Caption line in `--text-secondary`) + optional 24px action icon. |
| Bottom bar | `--surface`, 1px `--divider` border, 10px top corners, glow shadow `0 0 6px rgba(197,206,224,.6)`. Five items, each at least 54px wide: 24px icon with 8px above, Navbar label below. Inactive `--text-secondary`, active `--primary` icon and `--brand-text` label. |
| Bottom drawer | A sheet from the bottom over `--overlay`: `--surface-overlay`, top corners rounded, a short grey handle (`#CCCCCC`), centred Subtitle 2 title, content, then a full-width primary button. |
| Buttons | Full width (343px), stacked 8px apart, primary on top. |

### Tablet (ours, 834–1279px)

Banco CTT has no tablet screens, and the token export's tablet values are empty. This is our layout:

| Part | Spec |
|---|---|
| Side menu | **Collapsed by default** to a 72px icon rail: the same 48px items, icon only, with the label as a tooltip. The collapse button expands it to the 200px menu as an overlay over the page (with `--overlay` behind it), so the content doesn't reflow. |
| Top bar | As desktop (72px). |
| Content | Fluid, with 24px side margins, up to the 968px desktop column. |
| Columns | **Landscape (≥ 1112px):** two columns with a 24px gap. **Portrait (834–1111px):** one column; the second column's blocks follow the first. |
| Secondary panels | Open as an overlay from the right, up to 400px wide, with `--shadow-float`. |
| Modals | As desktop (568px, centred). |
| Touch | Every target at least 44 × 44px. No hover-only actions. |

### Rules for all widths

- **Bands:** phone < 834px; tablet 834–1279px; desktop ≥ 1280px. The token breakpoints are 375, 834, 1112 and 1440/1512/1728/1920.
- **No horizontal page scroll.** Every flexible grid column is `minmax(0, 1fr)`, never a bare `1fr`: a bare `1fr` can't shrink below its content and pushes bars off-screen.
- Long titles shorten with an ellipsis. Bars drop low-priority controls before overflowing.
- **Modals:** 568px wide on desktop and tablet (the tokens' "action" width); a bottom drawer on phone.
- **Icons:** 24px, 16px for inline actions such as "copy". One outline set, in `currentColor`.
- **Illustrations:** 40px in banners, 104px in feature cards **(Figma)**. The tokens also define 60, 166 and 194px.

## Elevation & Depth

- **Light (Figma):** most cards are **flat**: white on the `#F7F9FC` page is enough. Cards that carry their own action (a card with buttons, a profile card, an accordion header) use `--shadow`: `0 5px 6px rgba(197,206,224,.5)`. The phone bottom bar uses the `0 0 6px` glow at 60%.
- **Dark (ours):** no card shadow. Cards are `--surface` with a 1px `--card-outline`. Floating layers (menus, popovers, the expanded tablet menu) use `--surface-raised` with `--shadow-float`.

## Shapes

**Radius (Figma):**

| Radius | Use |
|---|---|
| **4px** | Buttons, toast, top corners of filled inputs |
| **6px** | Small logo badges (40px) |
| **10px** | Cards, list containers, banners and feedback blocks, modals, side-menu items, quick-action tiles and their icon badges, the phone bottom bar's top corners |
| **6px on a 12px bar** | Progress bars (fully rounded) |
| **Full (circle or pill)** | Radios, toggle, avatars, the collapse button, chips (tokens) |

The token export also defines 8px and 40px. No screen uses them.

**Borders:** 1px. Cards have **no border** in light. Dividers inside cards are 1px `--divider`.

**Focus (ours; the screens show no focus state):** a 2px `--primary` outline with a 2px offset on every interactive element (`:focus-visible`). Inputs show focus on the underline instead.

## Components

The colours below are roles (Colors › Role values). Each spec says where it comes from: **(Figma)** the real screens, **(tokens)** the token export, **(ours)** this document.

### Buttons

**(Figma)** 48px tall, **4px radius**, padding 12 × 24px, Button text (Bold 14 / 24.5px), centred. In forms the button fills its container up to **343px**. Stack buttons vertically 8px apart, primary on top.

| Variant | Background | Text | Border | Source |
|---|---|---|---|---|
| Primary | `--primary` | white | – | Figma |
| Primary, disabled | `--primary-disabled` | white | – | Figma |
| Primary, hover / pressed | `--primary-hover` / `--primary-active` | white | – | tokens |
| Secondary | transparent | `--brand-text` | 1px `--primary` | Figma |
| Secondary, disabled | transparent | `--primary-disabled` | 1px `--primary-disabled` | Figma |
| Secondary, hover / pressed | `--surface-active` / `--primary-tint` | `--brand-text` | 1px `--primary` | tokens |
| Ghost (text only) | transparent; hover `--surface-active` | `--brand-text` | – | tokens |
| Icon button | transparent; hover `--surface-hover` | `--text` icon, 24px (16px inline) | – | Figma size, tokens states |

- **One primary per view.**
- Compact toolbars may use a 32px-tall button with 16px side padding (ours).
- A destructive confirmation uses Primary with an explicit verb ("Eliminar gravação"). The system has no separate danger colour.

### Text input and select (filled)

**(Figma)**
- **Field:** `--surface-field`, exactly 48px tall, top corners 4px, a 1px `--field-line` underline, padding 7 × 12px.
- **Label** inside the field, above the value: Input label (12px Regular) in `--text-weak`.
- **Value:** Paragraph 2 (14px) in `--text`.
- **Select:** the same field with a 24px chevron at the right in `--text-section`.
- A field usually sits inside a white card with 16px padding, under a section title.

**(tokens)** States:
- Hover: `--surface-field-hover`.
- Filled: underline `--field-line-filled`.
- Focused: underline `--field-line-selected`, 2px.
- Error: underline `--primary`, 2px, with a Caption message below in `--error-text`.
- Help: underline grey-blue-500 with a Caption message.
- Disabled: label and value `--text-disabled`.

**(ours)** Search uses the same field with a leading 24px icon. A textarea grows from 48px.

### Radio and checkbox

- **Radio (Figma):** 20px circle. Off: `--surface-field` fill, 1px `--control-border`. On: 1px `--primary` ring with a 12px `--primary` dot.
- **Checkbox (tokens + ours):** 20px, 4px radius, same off colours. On: `--primary` fill with a white check. Hover on: `--primary-active`.
- In a list, the control sits at the right end of the row.

### Toggle

**(Figma)** 52 × 32px, fully rounded. Off: `--surface-field` track with a 1px `--control-border`, knob left. On: `--primary` track, knob right. The knob is a 28px white circle. Disabled knob: grey-blue-300 (tokens).

### Tabs

**(Figma)**
- The row has a 1px `--divider` bottom border.
- Each tab is at least 100px wide, with 14px below the label.
- Labels are Subtitle 2: `--text-secondary` inactive, `--brand-text` active.
- The active tab has a 2px `--primary` bottom border.
- The row scrolls horizontally when it doesn't fit and never wraps.

### Lists

**(Figma)**
- **Container:** a `--surface` card with 10px radius, rows separated by 1px `--divider`.
- **Row:** at least 64px tall, 16px padding, 12px between parts.
- **Leading (optional):** a 40px badge. Either a logo badge (6px radius) or a category badge (10px radius, a `--cat-*` fill, 24px white icon).
- **Text:** title in Subtitle 2 `--text`; caption in Caption `--text-weak`, 4px below.
- **Label-and-value rows** (account data): the Caption label on top in `--text-weak`, the value below in Paragraph 2 `--text`. A 16px copy icon may follow the value.
- **Trailing (optional):** a 24px icon (chevron, arrow, edit) or a radio or toggle.
- **Accordion:** a list row with a chevron; the open content follows in the same card.
- **Section title** above the container: Subtitle 2 in `--text-section`, 8px above.

**(tokens)** Row hover `--surface-hover`; selected `--surface-active`.

### Cards

**(Figma)**
- **Plain card:** `--surface`, 10px radius, 16px padding, flat.
- **Feature card:** 40px padding, content centred: a 104px illustration, 24px gap, a Subtitle 2 title, 16px gap, Paragraph 2 text.
- **Action card** (text on the left, buttons on the right): `--shadow`, grey-blue title (`--chip-fixed` colour) in H6.
- **Figure card:** a Paragraph 2 caption in `--text-weak` over an H4 amount whose decimals are H6.

### Quick-action tile

**(Figma)** `--surface`, 10px radius, padding 16 × 8px, content centred with an 8px gap: a 40px `--primary` badge (10px radius, 24px white icon) over a two-line Paragraph 2 label. Sizes: 145 × 112px in a three-column grid (desktop), 200 × 132px large.

### Banner (promotional)

**(Figma)** `--surface`, 10px radius, 16px padding, 12px gap: a 40px illustration, a Subtitle 2 title in `--text` with Paragraph 2 text in `--text-weak`, and a 24px close icon at the top right.

### Feedback block (inline message)

**(Figma)** 10px radius, 16px padding, 12px gap: a 24px icon in `--text`, then text in `--text-title` (a Subtitle 2 title plus a Caption line, or Paragraph 2 alone), then an optional 24px arrow when the whole block is a link.

| Kind | Background |
|---|---|
| Info | `--container-info` (`#E3F0F0`) |
| Alert / pending | `--container-alert` (`#FFF1BF`) |
| Error | `--container-primary` (`#FBDFE3`) |

### Toast

**(Figma)** `--surface-inverse` (`#333333`) with white Paragraph 2 text, 4px radius, padding 12 × 16px, 343px wide. Fixed 48px from the bottom and right on desktop; full width above the bottom bar on phone (ours). **Success and error look the same**: the text carries the meaning.

### Modal and drawer

**(Figma)**
- **Scrim:** `--overlay` (`#333333` at 60%).
- **Modal (desktop):**
  - 568px wide, `--surface-overlay` (`#F7F9FC`), 10px radius, centred, 40px bottom padding.
  - Header: 74px, centred Subtitle 2 title in `--text-title`.
  - Body: 16px side padding and 24px between blocks. Lists inside are white cards.
  - Actions: a 343px button stack, centred.
- **Drawer (phone):** the same content in a bottom sheet (Layout).
- **Loading error inside a modal:** an error feedback block at the top, skeleton rows below, and the primary button disabled.

### Skeleton (loading)

**(Figma)** `--skeleton` (`#EBEBEB`) rectangles replace each line of text: about 80 × 14px for a label and 120 × 14px for a value, with no rounding. Buttons that depend on the data are disabled while loading.

### Progress bar

**(Figma)** 12px tall, fully rounded; track `#EBEBEB` (`--skeleton`), fill in a `--cat-*` colour; a Badge-style percentage (Bold 12) at the right, 8px away.

### Avatar

**(Figma)** Circle, 24px (top bar, menu) or 40px (profile). Without a photo: `--container-primary` background with Subtitle 2 initials in `--text`.

### Chips and tags

**(tokens; no screen shows them)**
- **Fixed chip (choice):** selected = `--chip-fixed` fill with `--text-on-inverse` text; unselected = `--chip-fixed` text and outline. Pill-shaped, 32px tall, Caption text.
- **Fluid chip (filter):** `--chip-fluid` fill, hover `--surface-active`; the close icon sits on a `--surface-page` circle.
- **Status tag (ours):** a 22px pill in a container colour with `--text`, Badge text.
- **Count badge (ours):** an 18px `--primary` pill with white Badge text.

### Data table (ours)

Banco CTT's screens have no tables. This spec follows the list styling:
- **Container:** a `--surface` card, 10px radius, no outer border in light (1px `--card-outline` in dark). The card scrolls horizontally on narrow screens; the page never does.
- **Header row:** 48px tall, Subtitle 2 in `--text-section`, a 1px `--divider` below, no fill. A sortable header shows a 16px arrow; the sorted column's label is `--text`.
- **Body rows:** at least 48px tall (64px when a cell has two lines), 16px cell padding, Paragraph 2 in `--text`, separated by 1px `--divider`. No zebra stripes.
- **Alignment:** text left; numbers and amounts right, with tabular figures; actions right, as 24px icon buttons.
- **States:** row hover `--surface-hover`; selected `--surface-active`. Selection uses a checkbox in the first column.
- **Cell content:** status as a status tag; a secondary line in Caption `--text-weak`.
- **Matrix tables** (a grid of options, such as permissions): keep the first column and the header row sticky; centre the controls in their cells.
- **Empty and loading:** an empty table shows one centred Paragraph 2 line in `--text-weak`; a loading table shows skeleton rows.
- **Phone:** a table with more than three columns becomes a list: one card per row, each cell a label-and-value row.

### Icons

**(Figma)** Outline icons, 24px, in `--text`; red when active in navigation; white on a coloured badge. The tokens define ten icon colours: default, primary, inactive, white, secondary 300/500/600, alert, success, disabled.

## Do's and Don'ts

**Do**
- Use one primary (red) button per view, with a secondary (red outline) below or beside it.
- Put white cards on the pale blue-grey page. Keep them flat unless the card carries its own action.
- Use grey-blue for everything secondary: inactive tabs, navigation labels, chips, help text.
- Build inputs as filled fields with the label inside and an underline.
- Use Bold for titles, tabs, list titles and buttons, and Regular for everything else.
- Use role variables everywhere, and check every screen in both themes.
- Mark states in more than colour: an icon and text for errors, an underline for the active tab.

**Don't**
- Round buttons into pills or give them shadows.
- Fill the active menu item with a background: it's red text and a red icon only.
- Use red for decoration or for long text.
- Colour a toast by status: it's the same dark box for success and error.
- Use the light theme's link teal, `#999` section grey or `#8F9BB3` grey-blue for body-size text that must be read (see Colors › Contrast).
- Put borders on cards in the light theme, or shadows on cards in the dark theme.
- Hard-code primitives (`#E00024`, `color-red-500`) in product code.

## Content, imagery, motion

- **Language:** European Portuguese for customer-facing copy. Write labels as verbs ("Guardar", "Carregar") and keep sentences short.
- **Numbers and amounts:** use tabular figures (`font-variant-numeric: tabular-nums`) in tables and metrics.
- **Imagery:** illustrations at the five sizes, hidden on phone. Photos sit in radius-xl frames.
- **Skeletons:** `--skeleton` blocks for loading content. Use neutral-200 for a second tone.
- **Motion:** `--dur-fast` (150ms) for colour, underline and toggle changes, and `--dur-base` (200ms) for panels, with the `--ease` curve. No bounce. Respect `prefers-reduced-motion` (disable non-essential animation). Theme changes are instant.

## Accessibility

- Text contrast is at least 4.5:1, and 3:1 for large text (≥ 24px, or Bold ≥ 18.66px). Check every new pair against Colors › Contrast. Never introduce a text colour outside the role table.
- Don't use colour as the only signal: errors get an icon and text; categorical colours get a label; the active tab also gets the underline.
- Every interactive element has `:focus-visible` (Shapes) and is reachable by keyboard. Drawers and overlays trap focus and close on Escape.
- Touch targets are at least 44×44px on phone.
- Respect `prefers-reduced-motion` and `prefers-color-scheme`.

## Implementation

### Token file

Copy `assets/tokens.css` into the frontend and import it before any other stylesheet. Its full content:

```css
/* Banco CTT design tokens — CSS custom properties (see references/DESIGN.md in the bancoctt-design skill).
   Light = Banco CTT's Figma token export + the values in its real screens (Figma file KT4rQSWoBxvuOCBHyWLm76).
   Dark = the theme defined in DESIGN.md, section Colors (Banco CTT has none).
   Theme switch: <html data-theme="light|dark">; no attribute = follow the OS. */

:root {
  /* type */
  --font-sans: 'Inter', system-ui, sans-serif;
  /* size / line height / letter spacing, as used in the real screens */
  --fs-h4: 34px;       --lh-h4: 38.1px;      --ls-h4: 0.25px;
  --fs-h5: 24px;       --lh-h5: 28.8px;      --ls-h5: 0;
  --fs-h6: 20px;       --lh-h6: 22.4px;      --ls-h6: 0.15px;
  --fs-p1: 16px;       --lh-p1: 24px;        --ls-p1: 0.44px;
  --fs-p2: 14px;       --lh-p2: 20px;        --ls-p2: 0.25px;
  --fs-subtitle: 14px; --lh-subtitle: 16px;  --ls-subtitle: 0.1px;
  --fs-button: 14px;   --lh-button: 24.5px;  --ls-button: 0;
  --fs-caption: 12px;  --lh-caption: 16px;   --ls-caption: 0.4px;
  --fs-badge: 12px;    --lh-badge: 14px;     --ls-badge: 0.29px;
  --fs-navbar: 10px;   --lh-navbar: 16px;    --ls-navbar: 0.33px;
  --fw-regular: 400; --fw-bold: 700;
  /* spacing, radius, borders, icons */
  --space-1: 4px; --space-2: 8px; --space-3: 12px; --space-4: 16px; --space-6: 24px; --space-8: 32px; --space-10: 40px; --space-12: 48px;
  --radius-sm: 4px; --radius-md: 6px; --radius-lg: 8px; --radius-xl: 10px; --radius-2xl: 40px; --radius-pill: 999px;
  --border-default: 1px; --border-lg: 2px;
  --icon-default: 24px; --icon-sm: 16px;
  /* layout and control sizes (measured in the real screens) */
  --menu-width: 200px; --menu-width-collapsed: 72px; --topbar-height: 72px; --content-width: 968px; --column-gap: 32px;
  --control-height: 48px; --button-max-width: 343px; --list-item-min-height: 64px; --modal-width: 568px;
  /* motion */
  --ease: cubic-bezier(.2, 0, 0, 1); --dur-fast: 150ms; --dur-base: 200ms;

  /* colour constants (same in both themes) */
  --primary: #E00024; --primary-active: #C4001F; --text-on-primary: #FFFFFF;
  --success: #00BFB4; --alert: #FFC800; --offline: #A681AB; --highlight: #B5CB32;

  /* colour roles — light */
  --surface-page: #F7F9FC; --surface: #FFFFFF; --surface-raised: #FFFFFF; --surface-bar: #F1F4F8; --surface-overlay: #F7F9FC;
  --surface-field: #F1F4F8; --surface-field-hover: #F7F9FC; --surface-hover: #F7F9FC; --surface-active: #F1F4F8;
  --surface-inverse: #333333;
  --divider: #E4E9F2; --control-border: #C5CEE0; --card-outline: transparent;
  --field-line: #CCCCCC; --field-line-filled: #666666; --field-line-selected: #000000;
  --text: #000000; --text-strong: #000000; --text-title: #333333; --text-weak: #666666; --text-section: #999999; --text-disabled: #CCCCCC;
  --text-secondary: #8F9BB3; --text-on-inverse: #FFFFFF;
  --brand-text: #E00024; --brand-text-on-tint: #C4001F; --link: #00BFB4; --error-text: #EC677D; --alert-text: #CC9500;
  --primary-hover: #EC677D; --primary-disabled: #FBDFE3; --primary-tint: #FBDFE3;
  --container-primary: #FBDFE3; --container-info: #E3F0F0; --container-alert: #FFF1BF;
  --container-offline: #F1EAF1; --container-highlight: #F0F0E3;
  --chip-fixed: #6E7B93; --chip-fluid: #E4E9F2;
  --overlay: rgba(51, 51, 51, 0.6); --skeleton: #EBEBEB;
  --shadow: 0 5px 6px 0 rgba(197, 206, 224, 0.5); --shadow-float: 0 0 6px 0 rgba(197, 206, 224, 0.5);
  --cat-0: #E00024; --cat-1: #00BFB4; --cat-2: #A681AB; --cat-3: #CC9500; --cat-4: #6E7B93; --cat-5: #A4BF00; --cat-6: #EC677D; --cat-7: #68396F;
  color-scheme: light;
}

/* colour roles — dark (explicit choice) */
:root[data-theme="dark"] {
  --surface-page: #12151B; --surface: #1A1E26; --surface-raised: #232833; --surface-bar: #171B22; --surface-overlay: #171B22;
  --surface-field: #242A35; --surface-field-hover: #2A303C; --surface-hover: #232833; --surface-active: #262B35;
  --surface-inverse: #F1F4F8;
  --divider: #2C3340; --control-border: #8F9BB3; --card-outline: #2C3340;
  --field-line: #6E7B93; --field-line-filled: #C5CEE0; --field-line-selected: #F1F4F8;
  --text: #F1F4F8; --text-strong: #FFFFFF; --text-title: #F1F4F8; --text-weak: #C5CEE0; --text-section: #8F9BB3; --text-disabled: #5C6578;
  --text-secondary: #A9B4C9; --text-on-inverse: #12151B;
  --brand-text: #EC677D; --brand-text-on-tint: #EC677D; --link: #66D8D3; --error-text: #FFA3B0; --alert-text: #FFC800;
  --primary-hover: #C4001F; --primary-disabled: #4A1520; --primary-tint: #3A1520;
  --container-primary: #4A1520; --container-info: #0F3B39; --container-alert: #3D3200;
  --container-offline: #35213A; --container-highlight: #2E3410;
  --chip-fixed: #C5CEE0; --chip-fluid: #2C3340;
  --overlay: rgba(0, 0, 0, 0.6); --skeleton: #232833;
  --shadow: none; --shadow-float: 0 4px 16px 0 rgba(0, 0, 0, 0.6);
  --cat-0: #EC677D; --cat-1: #33CBC4; --cat-2: #C8B1CB; --cat-3: #FFC800; --cat-4: #C5CEE0; --cat-5: #B5CB32; --cat-6: #FFA3B0; --cat-7: #A681AB;
  color-scheme: dark;
}

/* colour roles — dark (no explicit choice, the OS is dark) */
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --surface-page: #12151B; --surface: #1A1E26; --surface-raised: #232833; --surface-bar: #171B22; --surface-overlay: #171B22;
    --surface-field: #242A35; --surface-field-hover: #2A303C; --surface-hover: #232833; --surface-active: #262B35;
    --surface-inverse: #F1F4F8;
    --divider: #2C3340; --control-border: #8F9BB3; --card-outline: #2C3340;
    --field-line: #6E7B93; --field-line-filled: #C5CEE0; --field-line-selected: #F1F4F8;
    --text: #F1F4F8; --text-strong: #FFFFFF; --text-title: #F1F4F8; --text-weak: #C5CEE0; --text-section: #8F9BB3; --text-disabled: #5C6578;
    --text-secondary: #A9B4C9; --text-on-inverse: #12151B;
    --brand-text: #EC677D; --brand-text-on-tint: #EC677D; --link: #66D8D3; --error-text: #FFA3B0; --alert-text: #FFC800;
    --primary-hover: #C4001F; --primary-disabled: #4A1520; --primary-tint: #3A1520;
    --container-primary: #4A1520; --container-info: #0F3B39; --container-alert: #3D3200;
    --container-offline: #35213A; --container-highlight: #2E3410;
    --chip-fixed: #C5CEE0; --chip-fluid: #2C3340;
    --overlay: rgba(0, 0, 0, 0.6); --skeleton: #232833;
    --shadow: none; --shadow-float: 0 4px 16px 0 rgba(0, 0, 0, 0.6);
    --cat-0: #EC677D; --cat-1: #33CBC4; --cat-2: #C8B1CB; --cat-3: #FFC800; --cat-4: #C5CEE0; --cat-5: #B5CB32; --cat-6: #FFA3B0; --cat-7: #A681AB;
    color-scheme: dark;
  }
}
```

### Logo files

`assets/bancoctt-logo.svg` is the Banco CTT wordmark from the Figma file (83 × 18px, red "ctt", black "banco"). `assets/bancoctt-logo-dark.svg` is ours for the dark theme: the same wordmark with "banco" in `#F1F4F8`. Replace it with the official negative version if Banco CTT has one. Using the logo in a product needs Banco CTT's permission.

### Base styles

```css
body { margin: 0; font: var(--fw-regular) var(--fs-p2)/var(--lh-p2) var(--font-sans); letter-spacing: var(--ls-p2); color: var(--text); background: var(--surface-page); }
:focus-visible { outline: 2px solid var(--primary); outline-offset: 2px; }
```

### Generating tokens from the source

To regenerate `tokens.css` after the brand team updates the Figma export:
- Resolve `{token}` references in the order `core` → `semantic` → `component`.
- Convert sRGB floats with `round(x × 255)`.
- Rename tokens to the roles in Colors › Role values. Don't carry the export's names into code: they contain `&`, `%`, `(`, `)` and `?`, which need escaping in CSS, plus open questions such as `(apagar?)`.
- Keep the dark block from this document until the export has a real dark mode.

## Instructions for agents

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

## Known issues

1. **Dark mode is an unfinished placeholder.** In `component.dark`, nearly every value is pure white `#FFFFFF`, including:
   - all button, form, list, chip and control colours
   - the dividers
   - the tab labels and the active tab line

   It also has text-default black, the primary button dark grey `#333` with teal text, and the navbar labels `#333`. Applied as-is, the UI is white-on-white. `core` and `semantic` have no dark mode either. Colors's dark theme is a separate proposal.
2. **The tablet modes are empty.** `responsive.tablet-vertical` and `-horizontal` set every spacing, border, icon, illustration and modal value to `0`; only their breakpoints (834 / 1112px) are real. The `app` mode zeroes illustrations and modal widths.
3. **Two type scales exist.** The token export's 13 `novos-*` styles (Semi Bold 600, `lineHeight: 0`) differ from the styles the real screens use (Bold 700, with line heights and letter spacing). This document follows the screens (Typography).
4. **Spacing, border, icon and illustration tokens are marked "Por definir"** ("to be defined").
5. **Open questions are still in the token names:** `forms-assistivetext-(apagar?)` ("delete?") and `forms-select-(unificar-ao-input?)` ("merge into input?").
6. **The colour styles disagree with the variables.** `brand-200-main-red` (style) is `#F4A3AF` while `color-red-200` (variable) is `#FFA3B0`.
7. **Light-theme contrast failures** (Colors › Contrast): links, section titles, inactive tabs, primary-hover label, error and alert text, input underlines, control borders, the selected-chip label, and three of the categorical hues (below 3:1 on white).
8. **No component library was available.** Component specs are derived from the real screens (Components). States the screens don't show come from the token export or are ours, as marked.
9. **The real screens cover one flow** (salary domiciliation): 39 frames. Components that flow doesn't use (chips, checkboxes, text inputs with typed values, error states of fields, tables) are not verified against a real screen.
10. **Inconsistencies inside the Figma file:**
    - Tab labels are set in Arial Bold on the phone overview and in Inter elsewhere.
    - One feature-card title is tagged H6 but rendered at 14px.
    - Two variable collections name the same colours differently (`Brand/500 Main Red` and `color/primary/500`).
    - Some variables are marked `(apagar)` ("delete").
