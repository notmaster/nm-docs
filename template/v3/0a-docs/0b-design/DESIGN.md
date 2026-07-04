---
version: alpha
name: Practical Product System
description: A restrained, adaptable design system for workflow-heavy software products.
colors:
  primary: "#174EA6"
  primary-hover: "#123E82"
  on-primary: "#FFFFFF"
  secondary: "#5F6368"
  tertiary: "#B3261E"
  neutral: "#F8FAFC"
  surface: "#FFFFFF"
  surface-muted: "#F1F5F9"
  border: "#CBD5E1"
  text: "#111827"
  text-muted: "#475569"
  error: "#B3261E"
  on-error: "#FFFFFF"
typography:
  headline-lg:
    fontFamily: Inter
    fontSize: 32px
    fontWeight: 700
    lineHeight: 1.2
    letterSpacing: 0
  headline-md:
    fontFamily: Inter
    fontSize: 24px
    fontWeight: 650
    lineHeight: 1.25
    letterSpacing: 0
  body-lg:
    fontFamily: Inter
    fontSize: 18px
    fontWeight: 400
    lineHeight: 1.6
    letterSpacing: 0
  body-md:
    fontFamily: Inter
    fontSize: 16px
    fontWeight: 400
    lineHeight: 1.5
    letterSpacing: 0
  body-sm:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: 400
    lineHeight: 1.45
    letterSpacing: 0
  label-md:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: 600
    lineHeight: 1.2
    letterSpacing: 0
  caption:
    fontFamily: Inter
    fontSize: 12px
    fontWeight: 500
    lineHeight: 1.35
    letterSpacing: 0
rounded:
  none: 0px
  sm: 4px
  md: 6px
  lg: 8px
  full: 9999px
spacing:
  xs: 4px
  sm: 8px
  md: 16px
  lg: 24px
  xl: 32px
  2xl: 48px
  page-x: 24px
  page-y: 32px
components:
  page:
    backgroundColor: "{colors.neutral}"
    textColor: "{colors.text}"
    typography: "{typography.body-md}"
  muted-panel:
    backgroundColor: "{colors.surface-muted}"
    textColor: "{colors.text-muted}"
    rounded: "{rounded.lg}"
    padding: 16px
  divider:
    backgroundColor: "{colors.border}"
    textColor: "{colors.text}"
    height: 1px
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.on-primary}"
    typography: "{typography.label-md}"
    rounded: "{rounded.md}"
    padding: 12px
    height: 40px
  button-primary-hover:
    backgroundColor: "{colors.primary-hover}"
    textColor: "{colors.on-primary}"
  button-danger:
    backgroundColor: "{colors.error}"
    textColor: "{colors.on-error}"
    typography: "{typography.label-md}"
    rounded: "{rounded.md}"
    padding: 12px
    height: 40px
  card:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
    rounded: "{rounded.lg}"
    padding: 24px
  input:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
    typography: "{typography.body-md}"
    rounded: "{rounded.md}"
    padding: 12px
    height: 40px
---

# DESIGN

## Overview

This design system is a neutral starting point for practical software products, especially tools with repeated workflows, dense information, and administrator-facing screens. It should feel clear, calm, and operational rather than decorative or marketing-led.

The visual tone is direct and structured. Interfaces should prioritize scanability, predictable navigation, clear state changes, and fast comprehension. Use expressive styling only when it helps the user understand hierarchy, status, or action priority.

## Colors

The palette combines high-contrast text, quiet surfaces, and a single dependable primary action color.

- **Primary (`#174EA6`):** Used for the main action on a screen, selected states, focused controls, and key links.
- **Primary hover (`#123E82`):** Used only for hover or active treatment of primary actions.
- **Secondary (`#5F6368`):** Used for supporting labels, metadata, and secondary interface text.
- **Tertiary / Error (`#B3261E`):** Used for destructive actions, blocking errors, and critical status. Do not use it as general decoration.
- **Neutral (`#F8FAFC`):** Used for page backgrounds.
- **Surface (`#FFFFFF`):** Used for panels, forms, tables, and primary content areas.
- **Surface muted (`#F1F5F9`):** Used for subtle grouping, table headers, inactive regions, and low-emphasis blocks.
- **Border (`#CBD5E1`):** Used for dividers, outlines, table lines, and input borders.
- **Text (`#111827`):** Default readable text color.
- **Text muted (`#475569`):** Secondary text that still needs to remain legible.

Use one primary action color per view. Avoid gradients, decorative color fields, and large monochrome areas unless a product-specific design direction explicitly requires them.

## Typography

Typography uses a single sans-serif family, **Inter**, to keep the base template portable and easy to implement. If the target product has a brand font, replace the font family while preserving the hierarchy and line-height relationships.

- **headline-lg:** Page titles and major section headers.
- **headline-md:** Dialog titles, panel headings, and major subsection headings.
- **body-lg:** Introductory copy or important readable explanations.
- **body-md:** Default body text, form text, and table content.
- **body-sm:** Supporting text, helper text, compact rows, and secondary details.
- **label-md:** Buttons, form labels, tabs, and short command labels.
- **caption:** Timestamps, metadata, compact status notes, and small annotations.

Letter spacing is `0` by default. Do not use negative tracking. Use stronger weight and spacing, not oversized text, to create hierarchy inside dense product surfaces.

## Layout

Use a simple spacing scale based on 4px and 8px increments. Default page padding is `24px` horizontally and `32px` vertically. Compact screens may reduce page padding to `16px`.

Favor structured layouts over decorative cards. Use full-width sections or simple constrained content areas for major page regions. Use cards only for repeated items, dialogs, forms, and content that genuinely needs a frame.

For workflow screens, place navigation and persistent controls in predictable locations. Primary actions should appear near the task context they affect. Tables, lists, and forms should preserve alignment so users can scan and compare information quickly.

## Elevation & Depth

Depth is conveyed through borders, spacing, surface contrast, and hierarchy rather than heavy shadows. Use shadows sparingly for overlays, menus, popovers, and dialogs that must visually detach from the page.

If shadows are added in implementation, keep them subtle and functional. Do not use glow, bokeh, or decorative depth effects as a background treatment.

## Shapes

The default shape language is modest and utilitarian. Rectangular UI elements use small radii to stay precise and compact.

- Use `4px` to `8px` radii for most controls and cards.
- Use `9999px` only for pills, avatars, and intentionally circular controls.
- Do not mix highly rounded cards with sharp inputs in the same surface.
- Keep cards at `8px` radius or less unless product-specific design requirements say otherwise.

## Components

**Buttons:** Use primary buttons for the single highest-priority action in a view. Secondary and tertiary actions should be quieter and should not compete with the primary action. Destructive actions use the error color and should include clear labels.

**Inputs:** Inputs use white surfaces, readable body text, and clear borders. Focus states should use the primary color. Error states should use the error color and include text feedback, not only color.

**Cards and panels:** Cards use white surfaces, subtle borders, and `24px` internal padding by default. Avoid nesting cards inside cards. Use section spacing before adding another framed container.

**Tables and lists:** Use consistent row height, clear dividers, and muted headers. Important status should be represented with text plus color or icon, not color alone.

**Navigation:** Navigation should remain predictable and compact. Highlight the active item with primary color or a subtle muted surface. Avoid large decorative navigation treatments in operational tools.

**Dialogs and popovers:** Use them for focused decisions or short forms. Keep headings compact, actions clear, and destructive confirmation explicit.

## Do's and Don'ts

- Do use the primary color for the most important action or selected state.
- Do maintain WCAG AA contrast for normal text and critical controls.
- Do keep spacing, alignment, and typography consistent across repeated elements.
- Do favor plain surfaces, borders, and clear hierarchy for operational screens.
- Don't introduce unrequested decorative gradients, blobs, glow effects, or ornamental backgrounds.
- Don't create a UI dominated by variations of a single hue.
- Don't use cards as page sections or nest cards inside other cards.
- Don't use color alone to communicate errors, success, warnings, or selection.
- Don't add new component styles unless they support a real product need.
