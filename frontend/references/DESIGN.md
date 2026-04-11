# Design System Document: The Precision Atlas

## 1. Overview & Creative North Star

### Creative North Star: "The Architectural Analyst"
This design system is built to bridge the gap between raw athletic energy and cold, mathematical precision. We are moving away from the "generic dark mode" dashboard. Instead, we are creating a high-end editorial experience that feels like a premium physical atlas. It is a "Blended" system: it utilizes the depth of deep charcoal tones, the warmth of soft clay, and the stark clarity of light-themed data surfaces.

The hallmark of this system is **Intentional Asymmetry**. We do not follow rigid, predictable grids. We use overlapping elements, floating glass panels, and varied typography scales to guide the eye through complex data. The experience should feel like looking through a high-tech lens at a classic sporting event—where precision data visualization (radar charts, heatmaps, and wagon wheels) sits atop sophisticated, layered textures.

---

## 2. Colors

The color palette is designed to create a "Blended" environment. We utilize deep tones for structural immersion and lighter, high-contrast surfaces for data consumption.

### The Palette (Material Design Tokens)
*   **Primary (Action):** `#FFB59F` / **Primary Container:** `#FF6D3F` (The Vibrant Orange)
*   **Background:** `#121416` (Deep Charcoal)
*   **Surface Tiers:**
    *   `surface_container_lowest`: `#0C0E10`
    *   `surface_container_low`: `#1A1C1E`
    *   `surface_container_high`: `#282A2C`
*   **Secondary (Tonal Clay):** `#CDC5BD`
*   **On-Surface (Typography):** `#E2E2E5`

### The "No-Line" Rule
**Strict Mandate:** Designers are prohibited from using 1px solid borders to section content. Boundaries must be defined solely through background color shifts. A `surface_container_low` card sitting on a `surface` background provides enough contrast to be seen without the "boxed-in" feel of a stroke. 

### Surface Hierarchy & Nesting
Treat the UI as physical layers.
*   **Base:** `surface_dim` (#121416).
*   **Sections:** Use `surface_container_low` for major page blocks.
*   **Data Cards:** Use `secondary_fixed` (#E9E1D9) for high-contrast, light-themed data cards. This "clay/off-white" shift signals a change from navigation to analysis.

### Glass & Gradient Rule
For floating overlays (e.g., player stats, quick filters), use Glassmorphism. Combine semi-transparent surface colors with a `backdrop-blur` (20px–40px). 
*   **Signature Textures:** Use subtle linear gradients on Primary CTAs, transitioning from `primary_container` (#FF6D3F) to `primary` (#FFB59F) at a 45-degree angle. This adds "soul" and prevents the vibrant orange from feeling flat.

---

## 3. Typography

The typography strategy pairs a high-tech, wide-set sans-serif for display with a highly legible, modern sans-serif for data-heavy body text.

*   **Display & Headlines (Space Grotesk):** This is our "Precision" font. Use `display-lg` (3.5rem) and `headline-lg` (2rem) to create editorial impact. It should feel architectural and sharp.
*   **Body & Titles (Manrope):** This is our "Functional" font. It offers superior readability for dense cricket statistics. Use `body-md` (0.875rem) for the majority of data points.
*   **Labeling (Manrope Bold):** All labels for charts (Wagon Wheels, Heatmaps) must use `label-md` (0.75rem) in all-caps with a +5% letter spacing to maintain the "Atlas" aesthetic.

---

## 4. Elevation & Depth

We convey hierarchy through **Tonal Layering** rather than drop shadows.

*   **The Layering Principle:** To lift a component, don't reach for a shadow; reach for a higher surface token. Place a `surface_container_highest` element on top of a `surface_container_low` background. The natural shift in charcoal tones creates a sophisticated, "quiet" depth.
*   **Ambient Shadows:** If an element must "float" (like a Modal or Tooltip), use a shadow color tinted with the primary brand hue: `rgba(255, 109, 63, 0.08)`. Use a large blur (32px) and zero spread to mimic soft, ambient light.
*   **The Ghost Border Fallback:** If accessibility requires a container edge, use the `outline_variant` token at 15% opacity. It should be felt, not seen.
*   **Glassmorphism Depth:** When using glass panels for AR-style overlays, the "frosted" effect allows background heatmaps to bleed through, ensuring the data feels integrated into the environment rather than pasted on top.

---

## 5. Components

### Buttons
*   **Primary:** Vibrant Orange (`primary_container`) with a 45° gradient. High-contrast white text. Roundedness: `md` (0.75rem).
*   **Secondary:** Glassmorphic base with a "Ghost Border."
*   **Tertiary:** No background, `title-sm` Manrope text, Orange icon.

### Data Visualization Units (Signature)
*   **Pitch Maps (Heatmaps):** Use a `surface_container_lowest` base. Heat intensity should scale from `surface_variant` to `primary`.
*   **Radar Charts:** Use `outline` tokens for the grid. The fill area should use `primary` at 20% opacity with a 2px `primary` stroke.
*   **Wagon Wheels:** Circular diagrams must use the `secondary_fixed` (clay) background for maximum contrast against the charcoal UI.

### Data Cards
*   **Style:** No borders. Use `secondary_fixed` (#E9E1D9) for the background. 
*   **Spacing:** Use `lg` (1rem) internal padding. 
*   **Separation:** Forbid dividers. Use 24px of vertical whitespace to separate list items within the card.

### Input Fields
*   **Style:** Minimalist. Only a bottom "Ghost Border" that transitions to a 2px `primary` line on focus.
*   **Labels:** Always floating `label-sm` to maintain the technical, "instrument panel" look.

---

## 6. Do's and Don'ts

### Do:
*   **Do** overlap elements. Let a data card slightly overlap a background radar chart to create a sense of depth and "active" analysis.
*   **Do** use asymmetrical layouts. A 60/40 split is more editorial and high-end than a 50/50 split.
*   **Do** use the clay-colored surfaces for "deep dive" stats to give the user's eyes a break from the dark background.

### Don't:
*   **Don't** use pure black (#000000). Always use the charcoal `surface` tokens to maintain tonal richness.
*   **Don't** use 1px solid borders. It shatters the "glass and clay" illusion and makes the app look like a generic bootstrap template.
*   **Don't** use standard "drop shadows." If it doesn't look like ambient light, don't use it.
*   **Don't** crowd the data visualization. Let heatmaps and charts breathe with at least 32px of margin.

---
*Director's Note: Precision is not about clutter; it is about the clarity of the most important detail. Use the orange sparingly to lead the eye, and let the tonal backgrounds do the heavy lifting of organization.*