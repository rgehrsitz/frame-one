/*
 * Frame One desk case
 *
 * A deliberately quiet, low-profile enclosure for a Waveshare 7.5-inch
 * e-Paper V2/V3 panel and Raspberry Pi Zero 2 W.  It is a parametric source
 * model, not a vendor-specific, ready-to-sell CAD file: measure the display
 * and connector stack you have before committing a long print.
 *
 * The visible face is intentionally simple: a 1.2 mm reveal around the EPD,
 * a wide white border, and a separate, slightly proud plinth.  The hardware
 * lives entirely behind the screen.
 *
 * Targets a Bambu Lab A1 mini (180 x 180 mm printable bounding boxes). The
 * wide front is a four-rail frame; its seams fall at the frame corners rather
 * than running through the screen. Export one part at a time below.
 */

part = "assembly"; // [assembly:Assembly,bezel_left:Bezel left,bezel_right:Bezel right,bezel_top:Bezel top,bezel_bottom:Bezel bottom,rear_left:Rear left,rear_right:Rear right,plinth_left:Plinth left,plinth_right:Plinth right]

// -- Display fit -----------------------------------------------------------
// Waveshare 7.5-inch e-Paper V2/V3: active 163.2 x 97.92 mm, bonded outline
// 177.2 x 118.2 mm.  The pocket is intentionally 0.8 mm oversize for an
// ordinary FDM printer; reduce `display_clearance` only after a test fit.
active_w = 163.2;
active_h = 97.92;
display_w = 177.2;
display_h = 118.2;
display_clearance = 0.8;

// -- Printed form ----------------------------------------------------------
body_w = 194;
body_h = 132;
bezel_t = 3.2;
face_lip_t = 1.2;
rear_d = 23;
wall = 2.4;
corner_r = 4;
window_clearance = 1.0;
frame_inner_x = (active_w + window_clearance) / 2;
frame_inner_y = (active_h + window_clearance) / 2;

// A1 mini-friendly, separate base. Its shallow front rail produces the
// framed-object silhouette without asking the e-paper panel to carry weight.
plinth_w = 200;
plinth_d = 31;
plinth_h = 16;
plinth_wall = 2.4;

// -- Fasteners -------------------------------------------------------------
// Four M3 x 20 socket-head screws close the rear shell into heat-set inserts
// in the bezel.  Set false for the clean, no-fastener visualisation only.
show_fasteners = false;
m3_clearance = 3.3;
insert_d = 4.6;
insert_depth = 4.5;
boss_r = 4.2;
boss_h = 6;
fastener_x = 91;
fastener_y = 54;

eps = 0.02;

module rounded_rect(w, h, r) {
    hull() {
        for (x = [-w / 2 + r, w / 2 - r])
            for (y = [-h / 2 + r, h / 2 - r])
                translate([x, y]) circle(r = r, $fn = 32);
    }
}

module rounded_box(w, h, d, r) {
    linear_extrude(height = d) rounded_rect(w, h, r);
}

module screw_positions() {
    for (x = [-fastener_x, fastener_x])
        for (y = [-fastener_y, fastener_y])
            translate([x, y, 0]) children();
}

// Crop the visual assembly into A1-mini-printable modules. The front-frame
// boundaries follow the aperture corners, like a conventional picture frame;
// the front never receives a distracting straight seam across the display.
module crop(x0, x1, y0, y1) {
    intersection() {
        children();
        translate([x0, y0, -1]) cube([x1 - x0, y1 - y0, 40]);
    }
}

module front_bezel() {
    pocket_w = display_w + display_clearance;
    pocket_h = display_h + display_clearance;
    aperture_w = active_w + window_clearance;
    aperture_h = active_h + window_clearance;

    difference() {
        union() {
            rounded_box(body_w, body_h, bezel_t, corner_r);
            // The bosses are entirely behind the visible front face, so the
            // assembled object has no visible hardware.
            screw_positions()
                translate([0, 0, bezel_t - eps])
                    cylinder(h = boss_h, r = boss_r, $fn = 32);
        }

        // Reveal the active EPD from the front, then create a wider rear
        // pocket.  The resulting 1.2 mm shelf protects the fragile glass and
        // sets its front plane consistently below the bezel.
        translate([0, 0, -eps])
            linear_extrude(height = face_lip_t + 2 * eps)
                rounded_rect(aperture_w, aperture_h, 0.6);
        translate([0, 0, face_lip_t])
            linear_extrude(height = bezel_t - face_lip_t + eps)
                rounded_rect(pocket_w, pocket_h, 1.2);

        // Heat-set insert pockets are cut from the rear.  Use a temperature
        // appropriate for the filament; do not force inserts into a cold
        // print, which can split the thin side walls.
        screw_positions()
            translate([0, 0, bezel_t + boss_h - insert_depth])
                cylinder(h = insert_depth + eps, r = insert_d / 2, $fn = 32);
    }
}

module rear_shell() {
    shell_w = body_w - 4;
    shell_h = body_h - 4;
    back_t = 2.4;

    difference() {
        rounded_box(shell_w, shell_h, rear_d, corner_r);

        // Hollow from the display side.  The unbroken rear plane leaves room
        // for the Pi, driver HAT, short cable loop, and an optional thin foam
        // pad. It is intentionally not a board-specific snap mount.
        translate([0, 0, -eps])
            rounded_box(shell_w - 2 * wall, shell_h - 2 * wall,
                        rear_d - back_t + eps, max(corner_r - wall, 1));

        // Rear-access screws into the bezel's inserts.
        screw_positions()
            translate([0, 0, rear_d - back_t - eps])
                cylinder(h = back_t + 2 * eps, r = m3_clearance / 2, $fn = 24);

        // A generous, downward-facing cable throat preserves the clean front
        // while accommodating USB-C or micro-USB power leads on either side.
        translate([-18, -shell_h / 2 - eps, rear_d - 13])
            cube([36, wall + 2 * eps, 14]);

        // Passive vents are on the rear's upper third, invisible in normal
        // desk use. The Pi Zero is low-power, so they are intentionally few.
        for (x = [-45 : 9 : 45])
            translate([x, shell_h / 2 - wall - eps, rear_d - 11])
                cube([4, wall + 2 * eps, 7]);
    }
}

module bezel_left() {
    crop(-body_w / 2 - eps, -frame_inner_x, -body_h / 2 - eps, body_h / 2 + eps)
        front_bezel();
}

module bezel_right() {
    crop(frame_inner_x, body_w / 2 + eps, -body_h / 2 - eps, body_h / 2 + eps)
        front_bezel();
}

module bezel_top() {
    crop(-frame_inner_x, frame_inner_x, frame_inner_y, body_h / 2 + eps)
        front_bezel();
}

module bezel_bottom() {
    crop(-frame_inner_x, frame_inner_x, -body_h / 2 - eps, -frame_inner_y)
        front_bezel();
}

module rear_left() {
    crop(-body_w / 2, eps, -body_h / 2, body_h / 2)
        rear_shell();
}

module rear_right() {
    crop(-eps, body_w / 2, -body_h / 2, body_h / 2)
        rear_shell();
}

module plinth() {
    // A low, solid front rail grounds the object visually and protects the
    // lower edge of the screen without putting point-load on its glass.
    difference() {
        hull() {
            translate([0, -plinth_d / 2, 0])
                rounded_box(plinth_w, plinth_d, 2, 3);
            translate([0, -plinth_d / 2 + 4, plinth_h - 2])
                rounded_box(plinth_w - 4, plinth_d - 7, 2, 3);
        }
        // Cable path out the rear underside.
        translate([-22, plinth_d / 2 - plinth_wall - eps, 0])
            cube([44, plinth_wall + 2 * eps, 8]);
    }
}

module plinth_left() {
    crop(-plinth_w / 2, eps, -plinth_d / 2, plinth_d / 2)
        plinth();
}

module plinth_right() {
    crop(-eps, plinth_w / 2, -plinth_d / 2, plinth_d / 2)
        plinth();
}

module assembly() {
    color("white") front_bezel();
    translate([0, 0, bezel_t]) color("gainsboro") rear_shell();
    // The plinth's broad base is on the desk; it overlaps the lower 16 mm of
    // the body as the clean, continuous front rail seen from a seated desk.
    translate([0, -body_h / 2 + plinth_h, 0])
        rotate([90, 0, 0]) color("white") plinth();
    if (show_fasteners)
        screw_positions()
            translate([0, 0, bezel_t + rear_d - 2.4])
                color("dimgray") cylinder(h = 1, r = 3.4, $fn = 24);
}

if (part == "bezel_left")
    bezel_left();
else if (part == "bezel_right")
    bezel_right();
else if (part == "bezel_top")
    bezel_top();
else if (part == "bezel_bottom")
    bezel_bottom();
else if (part == "rear_left")
    rear_left();
else if (part == "rear_right")
    rear_right();
else if (part == "plinth_left")
    plinth_left();
else if (part == "plinth_right")
    plinth_right();
else
    assembly();
