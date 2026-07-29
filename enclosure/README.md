# Frame One enclosure

Frame One uses the fit-proven magnetic enclosure in
[`EInk7.5-Frame-Magnets-4x2mm.3mf`](EInk7.5-Frame-Magnets-4x2mm.3mf). Open this
3MF directly in Bambu Studio or another compatible slicer; it contains the
front bezel and rear housing in the intended print profile.

## Compatible hardware

- Waveshare 7.5-inch, 800 × 480 e-paper display
- Raspberry Pi Zero 2 W (or Pi Zero 1/2 WH)
- Compatible Waveshare 7.5-inch display HAT and FPC adapter
- Eight 4 × 2 mm magnets and super glue

## Print and assembly

The included profile specifies 0.12 mm layers, two walls, and 12% infill. PLA
is the recommended material; PETG also works. Keep the supplied orientation
and painted supports unless a slicer preview shows they are not needed.

1. Print both parts in the 3MF and remove supports carefully.
2. Glue eight 4 × 2 mm magnets into the pockets, checking the polarity before
   the adhesive cures.
3. Set the display HAT's display switch to **B** and interface switch to **0**.
4. Connect the FPC cable to the e-paper adapter, then slide the display into
   the bezel without stressing the cable.
5. Stack the Pi and HAT below the panel, route the cable beneath the stack, and
   snap the rear housing onto the magnetic bezel.

Always shut the Pi down before disconnecting its power. The FPC cable and
e-paper glass are delicate: do not force either while closing the enclosure.

## Model provenance

This print profile is the supplied **E-Ink Weather Display Frame** by
`dbunndesign` and retains the license embedded in the 3MF: **MakerWorld
Exclusive License**. Do not modify or redistribute it outside the terms of
that license. The previous custom OpenSCAD enclosure and its generated STL
parts have been removed from this project.
