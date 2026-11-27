// Ask Elmer key box: a small clip-on box for the CardputerZero that holds
// the paddle jack and the key-out jack (with its optocoupler), wired to the
// EXT header by a short 2x7 ribbon or Dupont lead.
//
//   openscad -o elmer_key_box_body.stl -D part=\"body\" elmer_key_box.scad
//   openscad -o elmer_key_box_lid.stl  -D part=\"lid\"  elmer_key_box.scad
//
// MEASURE YOUR CARDPUTER FIRST: set device_t (its thickness where the clip
// grips) and check where the EXT header sits before printing. Print in PETG
// or PLA, 0.2 mm layers, no supports (body opening up, lid flat).

part = "both";          // "body", "lid" or "both"

// ---- box ----
box_l = 58;             // along the Cardputer's edge
box_w = 30;             // away from it
box_h = 16;             // height of the box
wall  = 2;
lid_t = 1.6;
r     = 3;              // corner radius

// ---- jacks (3.5 mm panel jacks, e.g. PJ-392 / Switchcraft 35RAPC) ----
jack_d   = 6.2;         // panel hole for the threaded bush
jack_z   = 8;           // centre height above the floor
jack_x   = [16, 42];    // paddle in, key out (from the left end)

// ---- the lead to the EXT header ----
lead_w = 11;            // slot for a 2x7 ribbon / Dupont lead
lead_h = 6;

// ---- clip that hugs the Cardputer's edge ----
device_t = 19.5;        // Cardputer thickness where it clips: MEASURE
clip_depth = 9;         // how far the jaws reach over the case
clip_t = 2.2;           // jaw thickness (springy in PETG)
clip_len = 40;
grip = 0.4;             // interference so it holds

// ---- PCB (a 5 x 7 hole piece of perfboard is plenty) ----
pcb_l = 30; pcb_w = 20; pcb_t = 1.6; standoff = 3;

$fn = 48;

module rbox(l, w, h, rr) {
    hull() for (x = [rr, l - rr], y = [rr, w - rr]) translate([x, y, 0]) cylinder(r = rr, h = h);
}

module body() {
    difference() {
        rbox(box_l, box_w, box_h, r);
        translate([wall, wall, wall]) rbox(box_l - 2 * wall, box_w - 2 * wall, box_h, r - 1);
        // jack holes in the long outer wall
        for (x = jack_x) translate([x, box_w + 1, jack_z]) rotate([90, 0, 0]) cylinder(d = jack_d, h = wall + 2);
        // lead slot in the inner wall (towards the Cardputer)
        translate([box_l / 2 - lead_w / 2, -1, wall + 2]) cube([lead_w, wall + 2, lead_h]);
        // labels, engraved 0.6 mm
        translate([jack_x[0], box_w - 0.6, jack_z - 5.6]) rotate([90, 0, 180]) label("PADDLE");
        translate([jack_x[1], box_w - 0.6, jack_z - 5.6]) rotate([90, 0, 180]) label("KEY OUT");
    }
    // PCB standoffs with M2 pilot holes
    for (x = [0, pcb_l - 4], y = [0, pcb_w - 4])
        translate([(box_l - pcb_l) / 2 + 2 + x, (box_w - pcb_w) / 2 + 2 + y, wall])
            difference() { cylinder(d = 4.5, h = standoff); cylinder(d = 1.7, h = standoff + 1); }
    clip();
}

module label(t) {
    translate([0, 0, 0]) linear_extrude(1) text(t, size = 3, halign = "center", valign = "center",
                                                font = "Liberation Sans:style=Bold");
}

// A U-shaped clip under the box: the Cardputer's edge slides between the jaws.
module clip() {
    gap = device_t - grip;
    translate([(box_l - clip_len) / 2, 0, 0]) {
        // back plate (shared with the box's inner wall)
        translate([0, -clip_t, 0]) cube([clip_len, clip_t, box_h]);
        // lower jaw, under the Cardputer
        translate([0, -clip_t - clip_depth, 0]) cube([clip_len, clip_depth + clip_t, clip_t]);
        // upper jaw, over the Cardputer: the box sits beside the device, so
        // the jaw is a separate arm at device height
        translate([0, -clip_t - clip_depth, clip_t + gap]) cube([clip_len, clip_depth + clip_t, clip_t]);
        // spine joining both jaws
        translate([0, -clip_t, 0]) cube([clip_len, clip_t, clip_t * 2 + gap]);
        // small lips so it snaps on
        for (z = [clip_t, clip_t + gap - 0.8])
            translate([0, -clip_t - clip_depth, z]) cube([clip_len, 1.2, 0.8]);
    }
}

module lid() {
    union() {
        rbox(box_l, box_w, lid_t, r);
        translate([wall + 0.25, wall + 0.25, lid_t])
            difference() {
                rbox(box_l - 2 * wall - 0.5, box_w - 2 * wall - 0.5, 2, r - 1);
                translate([1.2, 1.2, -1]) rbox(box_l - 2 * wall - 2.9, box_w - 2 * wall - 2.9, 4, r - 2);
            }
        // the mark: speech bubble with dit dah dit, raised 0.6 mm
        translate([box_l / 2, box_w / 2, -0.01]) mirror([1, 0, 0]) mark();
    }
}

module mark() {
    translate([0, 0, -0.6]) linear_extrude(0.61) difference() {
        offset(r = 2) square([18, 10], center = true);
        translate([-6, 0]) circle(d = 2.6);
        translate([0, 0]) offset(r = 1.3) square([2.6, 0.01], center = true);
        translate([6, 0]) circle(d = 2.6);
    }
}

if (part == "body") body();
else if (part == "lid") lid();
else { body(); translate([0, box_w + 25, 0]) lid(); }
