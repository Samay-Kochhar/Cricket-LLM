# Design System Specification: Kinetic Glass

## 1. Overview & Creative North Star
The Creative North Star for this system is **"The Kinetic Observatory."** 

We are moving beyond static dashboards into a high-performance, analytical environment that feels like a premium heads-up display (HUD). This system rejects the "flat web" aesthetic in favor of a multi-dimensional workspace. By utilizing **Kinetic Glass**, we create a UI that feels light despite its data density, using translucent surfaces to maintain a connection to the underlying action (e.g., live sports, real-time data).

The experience is defined by **intentional asymmetry** and **tonal depth**. Rather than a rigid, boxed-in grid, elements should feel like they are floating in a 3D coordinate space. Large-scale typography and overlapping "frosted" panels create an editorial feel that is both authoritative and agile.

---

## 2. Colors & Surface Philosophy
The palette is rooted in deep obsidian tones (`#0a0e14`) contrasted against high-energy neon signals (`#9cff93`).

### The "No-Line" Rule
**Explicit Instruction:** Do not use 1px solid borders to define sections. Layout boundaries must be established through color shifts or material changes.
- Use `surface-container-low` against the `background` to imply a region.
- Use vertical white space and font weight to separate data points, never divider lines.

### Surface Hierarchy & Nesting
Treat the UI as physical layers of frosted glass.
*   **Base:** `surface` (#0a0e14) — The infinite dark void.
*   **Primary Containers:** `surface-container` (#151a21) at 80% opacity with `backdrop-blur: 20px`.
*   **Elevated Elements:** `surface-container-high` (#1b2028) at 60% opacity for nested modules.

### The "Glass & Gradient" Rule
Floating overlays must use **Glassmorphism**. Combine `surface-variant` at 40-60% opacity with a heavy `backdrop-filter: blur(12px)`. To provide "soul," apply a subtle **Radial Glow** in the corner of primary cards using a 10% opacity gradient of `primary` (#9cff93) to `transparent`.

---

## 3. Typography
We use a high-contrast typographic pairing to balance technical precision with aggressive sportiness.

*   **The Powerhouse (Space Grotesk):** Used for `display`, `headline`, and `title` scales. This font’s geometric quirks convey a futuristic, analytical vibe.
    *   *Usage:* Use `display-lg` (3.5rem) for hero stats and `headline-md` (1.75rem) for section headers.
*   **The Workhorse (Manrope):** Used for `body` scales. Its high legibility ensures that complex data remains readable at small sizes.
*   **The Technical Label (Inter):** Reserved for `label-md` and `label-sm`. These should be set in Uppercase with +5% letter spacing to mimic instrument readouts.

---

## 4. Elevation & Depth
Depth is achieved through **Tonal Layering**, not structural scaffolding.

*   **The Layering Principle:** Stack `surface-container` tiers to create "lift." A `surface-container-highest` card sitting on a `surface-container-low` section creates a natural hierarchy without visual clutter.
*   **Ambient Shadows:** For floating glass panels, use "Spectral Shadows." Instead of black, use a tinted shadow: `rgba(156, 255, 147, 0.08)` (a 8% tint of your primary green) with a 40px blur. This mimics the light refraction through green-tinted glass.
*   **The Ghost Border:** If a boundary is strictly required for accessibility, use `outline-variant` at **15% opacity**. It should be felt, not seen.
*   **Kinetic Glows:** Interactive elements should emit a soft glow (`primary_dim`) when active, suggesting the surface is "energized."

---

## 5. Components

### Buttons
- **Primary:** Background `primary` (#9cff93), text `on_primary`. Roundedness: `full`. No shadow, but a subtle glow on hover.
- **Secondary (Glass):** `surface-variant` at 30% opacity + `backdrop-blur`. Roundedness: `md`.
- **Tertiary:** No background. `primary` text with an underline that only appears on hover.

### Cards & Overlays
- **Analytical Cards:** Use `surface-container-highest` with a `backdrop-blur`. Roundedness: `xl` (1.5rem). 
- **Constraint:** Never use dividers. Use `body-sm` labels in `on_surface_variant` to categorize internal data.

### Chips (Data Tags)
- Use `secondary_container` for inactive states. 
- Active states use `primary_container` with `on_primary_container` text. Roundedness: `full`.

### Input Fields
- **Background:** `surface_container_lowest` (Pure black #000000) at 40% opacity.
- **Focus State:** 1px `Ghost Border` using `primary` at 40% opacity. No solid fills.

### Additional Component: The "Active Tracker"
- A specific component for this system: A translucent pill with a pulsing `primary_dim` dot to indicate real-time data streaming.

---

## 6. Do's and Don'ts

### Do
*   **Do** use overlapping elements. Let a card partially obscure a background graphic to enhance the "glass" effect.
*   **Do** lean into `Space Grotesk` for large numbers. The "Kinetic Glass" vibe relies on big, bold data points.
*   **Do** use `backdrop-blur` (16px+) on all floating menus to maintain context of the underlying UI.

### Don't
*   **Don't** use pure white (#FFFFFF) for text. Use `on_surface` (#f1f3fc) to prevent "light bleed" on dark backgrounds.
*   **Don't** use 100% opaque cards. Everything in this system should feel like it has a degree of transparency and "breathability."
*   **Don't** use standard drop shadows. If it looks like a "box shadow," it’s too heavy. It should look like "ambient light."
*   **Don't** use sharp corners. Stick to the `md` to `xl` roundedness scale to keep the "sporty/ergonomic" feel.