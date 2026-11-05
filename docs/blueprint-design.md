# PipeFoundry industrial blueprint

PipeFoundry's design uses warm graphite, copper tool details, cool teal
work surfaces and mint for primary actions. The overview opens with the
pipeline manifold and leads into configuration, validation and review.
The working routes use compact plates above familiar tools.

The reference study took the immediate product and action hierarchy from
[Trickee](https://www.trickee.co.in/) and the progression from luminous opening
art to a quieter functional destination from [Shunya Chakra](https://shunyachakra.com/#waitlist).
The PipeFoundry composition uses original engineering subjects instead of
reference artwork or branding. [Artwork inventory](blueprint-assets.md).

| System | Decision |
| --- | --- |
| Palette | Graphite `#171a18`, rail `#121714`, panel `#1c211e`, line `#39443e`, copper `#e9ad7e`, mint `#a3ebd6` |
| Typography | Segoe UI and system sans for interface text, native monospace for code and tooling labels, fluid headline sizes |
| Layout | Persistent desktop navigation, sticky command bar, framed plate, compact workspace and mobile drawer |
| Geometry | Fine graphite borders and restrained radii; three original illustration-backed overview chapters |
| Motion | A short entrance for the heading and mast image, scroll-linked plate crop and reading trace, native document scroll |
| Accessibility | Content starts visible, decorative images have empty alt, dimensions are reserved, and reduced motion disables the entrance and scroll effects |

The concept review compared the generated PipeFoundry board at 1672 × 941
with the rendered application.

| Comparison | Implementation and decision |
| --- | --- |
| Opening headline and action | “Build the release.” and the mint editor action match the board. Supporting copy describes actual typed configuration and review. |
| Art | A copper manifold with teal fittings uses the board's tooling anatomy as direction. The live illustration is a crisp, scalable blueprint instead of its photographic machine. |
| Shell and icons | Graphite rail, mint active state and consistent line icons preserve the real workbench navigation. |
| Operational sequence | Three overview chapters lead to the existing Configure, Validate and Review views. The five-step journey remains available on tool routes. |
| Work surfaces | The board's visual framing becomes compact route plates. Tables, source evidence, the editor and review controls remain live. |
| Mobile | The art stacks below the heading and the chapter cards become compact rows. The five-step journey fits in one row. |

The existing title “Overview” stays in navigation and metadata. The headline
becomes “Build the release.” The secondary action jumps to the three real
workbench steps. The board's sample dashboard claims and navigation categories
do not appear in the application.

The desktop table maintains its internal horizontal scrollbar on narrow
screens. During review a visually hidden table label expanded the document's
scroll width. The table scroller now contains that label, and the mobile grid
tracks can shrink without affecting table contents.

The Chrome viewport sweep caught a second overflow at 768 px in the five-step
journey. The steps now use five equal, shrinkable tracks when space is tight.
The final sweep covered all 16 views at 320, 390, 768, 1024, 1280, 1672 and
1920 px. All 112 layout checks passed with no document overflow. Chrome
decoded all 24 placed assets and logged no console errors or failed network
requests. Scrolling moved the reading trace from 0 to 47.7%. Reduced motion
disabled the mast, plate and trace animations. The editor validated a draft,
the artifact contained a real CronJob, and release review returned its
policy result and preserved the dated run proof.
[Browser checks](../evidence/blueprint-browser.json).

[Desktop at the concept's 1672 × 941 dimensions](../evidence/blueprint-desktop.png) ·
[Mobile at 390 × 844](../evidence/blueprint-mobile.png)
