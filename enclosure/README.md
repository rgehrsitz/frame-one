# Frame One desk case

This is the physical companion to the dashboard: a quiet, horizontal object
with a white frame, a deeply set paper-like screen, and a simple lower plinth.
It takes its cue from a small premium desk display rather than a Raspberry Pi
project box. There are no front-facing ports, logos, visible screws, or exposed
PCBs.

The source model is [`frame-one-desk-case.scad`](frame-one-desk-case.scad). It
is intentionally parametric and is the first fit-tested enclosure iteration,
not a promise that every Waveshare revision has identical mechanics.

## Supported reference hardware

- Waveshare 7.5-inch black-and-white e-Paper V2/V3 panel: 800 × 480
- Raspberry Pi Zero 2 W
- Waveshare 65 × 30.2 mm driver HAT, connected with a short GPIO cable or
  otherwise arranged flat behind the screen
- Four M3 heat-set inserts and four M3 × 20 mm socket-head screws
- Four small silicone feet and a 1–2 mm foam pad behind the panel

The model is based on Waveshare's published 177.2 × 118.2 mm bonded-screen
outline and 163.2 × 97.92 mm active area. Measure the outline, active area,
and your board/cable stack before printing the full case; some listings bundle
the raw 170.2 × 111.2 mm panel instead. Update the display parameters at the
top of the SCAD file if yours differs.

## Print and assemble

Open the model in OpenSCAD and export each `part`: `bezel_left`, `bezel_right`,
`bezel_top`, `bezel_bottom`, `rear_left`, `rear_right`, `plinth_left`, and
`plinth_right`. The `assembly` selection is a visual check only; the finished
object is deliberately wider than an A1 mini's 180 mm bed. Every printable
module fits the A1 mini. Print the bezel rails face-down, the rear parts with
their outside face on the bed, and the plinth halves on their underside (the
face that meets the desk), which leaves the seating channel opening upward.

Suggested starting profile:

- PLA or PETG in matte warm white; 0.20 mm layers; 3 perimeters; 15% gyroid
  infill.
- Disable supports. The geometry is designed to print without them.
- Print a 10 mm-wide strip of the bezel/pocket first. Confirm the screen drops
  into the rear pocket without force before starting the full 10–12 hour job.

Assembly sequence:

1. Dry-fit the four bezel rails around the panel, then wick a small amount of
   CA glue into each joint from the rear. The joins land at the frame corners,
   not across the display. Press the four M3 inserts into the two side rails.
2. Place the panel face-down in the bezel. The 1.2 mm lip holds only its outer
   inactive border; never press on the active glass.
3. Arrange the Pi, driver HAT, and cable in the rear shell, leaving slack at
   the downward cable throat. Add the foam pad only where it supports a border
   or electronics—not the active display.
4. Glue the rear and plinth halves together from their inside/rear faces. Close
   the shell with four M3 × 20 mm screws from the rear. Lower the finished case
   into the plinth's channel—it seats 9 mm deep and the stand, not the panel,
   carries the weight—then add silicone feet underneath.

The rear is intentionally an electronics volume rather than a rigid Pi/HAT
mount. This leaves the screen and its delicate flex cable serviceable and
avoids pretending that every cable arrangement is the same. A version-specific
Pi tray can be added once the exact panel revision, HAT orientation, and power
connector are confirmed.

## Design language

The target silhouette is approximately 200 mm wide, 132 mm high, and 26 mm
deep at the electronics body, seated 9 mm into a 16 mm plinth. The display sits
1.2 mm behind a flat front reveal, and the frame overlaps the panel by 6.5 mm
at the sides and 9.6 mm top and bottom.

The plinth is a separate seating trough rather than a glued-on rail: the case
drops into a full-width channel, so the stand carries the load and the panel is
never a structural member. Its 10 mm front wall is the continuous rail read
from a seated desk. Note the reference photo that informed this look uses a
much wider 10.85-inch panel; the proportions here are set by the 7.5-inch
panel's 177.2 × 118.2 mm outline, so the object is squarer than the reference.

Keep the printed front matte white or very pale warm gray. The e-paper's own
white becomes the visual field; avoid a black bezel, shiny silk filament, or a
large engraved wordmark, all of which compete with the screen.
