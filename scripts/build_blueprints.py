"""Build the original PipeFoundry technical plates using standard-library geometry."""

from math import cos, radians, sin
from pathlib import Path

from pipefoundry.blueprints import PAGE_ARTWORK, SECTION_ARTWORK

DEST = Path(__file__).resolve().parents[1] / "src/pipefoundry/web/art"
COPPER = "#e8a26b"
TEAL = "#83c7bc"
DIM = "#54726d"


def path(d, color=COPPER, width=1.5, *, fill="none", opacity=1):
    return (
        f'<path d="{d}" fill="{fill}" stroke="{color}" stroke-width="{width}" '
        f'opacity="{opacity}" stroke-linejoin="round" stroke-linecap="round"/>'
    )


def circle(x, y, radius, color=COPPER, fill="none", width=1.4):
    return (
        f'<circle cx="{x}" cy="{y}" r="{radius}" fill="{fill}" '
        f'stroke="{color}" stroke-width="{width}"/>'
    )


def box(x, y, width, height, color=COPPER, fill="#142021", radius=3):
    return (
        f'<rect x="{x}" y="{y}" width="{width}" height="{height}" rx="{radius}" '
        f'fill="{fill}" stroke="{color}" stroke-width="1.3"/>'
    )


def label(x, y, value, color=TEAL, size=9):
    return (
        f'<text x="{x}" y="{y}" fill="{color}" font-size="{size}" '
        f'font-family="monospace" letter-spacing="1.3">{value}</text>'
    )


def marks(x, y, count, step=17):
    return "".join(
        path(f"M{x + i * step} {y}v{7 if i % 4 == 0 else 3}", DIM, 1) for i in range(count)
    )


def pipe(d, color="copper", width=27):
    return (
        path(d, "#080d0d", width + 8)
        + path(d, f"url(#{color})", width)
        + path(d, "#fae0b9" if color == "copper" else "#b8efe6", 1.5, opacity=0.65)
    )


def rivets(x, y, rx, ry, count=8, color=COPPER):
    return "".join(
        circle(round(x + rx * cos(a), 2), round(y + ry * sin(a), 2), 2.6, color, "#141e1d")
        for i in range(count)
        for a in (radians(i * 360 / count),)
    )


def flange(x, y, size=26, color=COPPER):
    return (
        circle(x + 5, y + 5, size, "#4b3b2b", "#2a2420", 2)
        + circle(x, y, size, color, "#192421", 2.2)
        + circle(x, y, size * 0.53, color, "#0d1717")
        + rivets(x, y, size * 0.79, size * 0.79, color=color)
    )


def plate(x, y, width, depth, height=21, color=COPPER):
    slant = int(depth * 0.56)
    return (
        path(
            f"M{x} {y}l{slant} {depth}h{width}v{height}h{-width}l{-slant} {-depth}z",
            "#684d37" if color == COPPER else DIM,
            fill="#161f1e",
        )
        + path(f"M{x} {y}h{width}l{slant} {depth}h{-width}z", color, fill="url(#surface)")
        + path(
            f"M{x + 15} {y + 8}h{width - 28}l{slant - 8} {depth - 14}h{28 - width}z",
            color,
            0.7,
            opacity=0.6,
        )
        + circle(x + 15, y + 5, 2.2, color, "#101918")
        + circle(x + width - 12, y + 5, 2.2, color, "#101918")
    )


def sheet(x, y, width=155, height=123, color=COPPER):
    fold = 17
    drawing = path(
        f"M{x} {y}h{width - fold}l{fold} {fold}v{height - fold}h{-width}z",
        color,
        1.6,
        fill="url(#surface)",
    )
    drawing += path(f"M{x + width - fold} {y}v{fold}h{fold}", color)
    for i, w in enumerate((0.62, 0.45, 0.73, 0.55)):
        drawing += path(
            f"M{x + 19} {y + 34 + i * 15}h{int(width * w)}", TEAL if i % 3 else color, 1.1
        )
    return drawing


def scope(x, y, radius, color=TEAL):
    return (
        circle(x, y, radius, color)
        + circle(x, y, radius - 7, color, "#101d1d", 0.8)
        + path(
            f"M{x - radius - 13} {y}h{2 * radius + 26}M{x} {y - radius - 13}v{2 * radius + 26}",
            DIM,
            0.8,
        )
    )


def node(x, y, name, color=COPPER, width=92):
    return (
        box(x, y, width, 40, color)
        + circle(x + 13, y + 20, 3.3, color, color, 0)
        + label(x + 25, y + 23, name, color, 8)
    )


def manifold():
    return (
        plate(116, 251, 423, 50, 16, TEAL)
        + pipe("M83 196H212Q244 196 244 164V106Q244 75 277 75H461")
        + pipe("M244 151H421Q454 151 454 188V228H583", "teal", 29)
        + pipe("M367 75V119Q367 151 402 151H513Q549 151 549 117V86H641", width=22)
        + pipe("M300 151V228Q300 255 334 255H455", width=20)
        + flange(86, 195, 29)
        + flange(464, 75, 25)
        + flange(640, 86, 21)
        + flange(582, 228, 27, TEAL)
        + flange(455, 255, 19)
        + circle(367, 151, 34, COPPER, "#201f18", 2)
        + circle(367, 151, 21, COPPER, "#111c1c")
        + path("M367 133v36M349 151h36", TEAL, 2)
        + rivets(367, 151, 28, 28)
        + path("M121 165V131H169M498 54h83v-8", DIM)
        + label(124, 123, "INLET")
        + label(494, 40, "TRANSFORM")
        + label(570, 269, "SINK")
    )


def source_stack():
    return (
        sheet(222, 102, 196, 151, TEAL)
        + sheet(200, 81, 196, 151)
        + sheet(177, 60, 196, 151)
        + path("M408 151h62v-58h62m-62 58h62m-62 0v56h62", TEAL, 2)
        + node(532, 73, "HEAD", TEAL)
        + node(532, 131, "TREE")
        + node(532, 187, "BLOB", TEAL)
        + path("M141 72h-22v185h115", DIM)
        + marks(119, 258, 9)
    )


def junction():
    return (
        pipe("M85 171H232Q252 171 252 149V100H365", "teal", 15)
        + pipe("M252 149v92H365", width=15)
        + pipe("M456 100h73v70h90M456 241h73v-71", "teal", 13)
        + node(74, 151, "TRIGGER", TEAL, 98)
        + node(367, 80, "CHECK")
        + node(367, 221, "BUILD")
        + flange(252, 149, 25)
        + flange(619, 170, 28, TEAL)
        + label(550, 226, "JOIN")
        + marks(107, 271, 31)
    )


def raceway():
    return (
        box(120, 92, 516, 171, DIM, "#132120", 74)
        + box(146, 115, 464, 126, TEAL, "#142020", 58)
        + box(169, 138, 417, 80, COPPER, "#101919", 40)
        + path("M215 178h109l26-26h57l25 26h111", COPPER, 3)
        + "".join(
            circle(x, y, 6, TEAL, "#121e1e")
            for x, y in ((215, 178), (350, 152), (432, 178), (543, 178))
        )
        + label(120, 72, "JOB EXECUTION")
        + label(508, 282, "QUEUE / COMPLETE")
        + marks(232, 265, 19)
    )


def oscillograph():
    return (
        box(98, 68, 560, 218, DIM, "#111e1e")
        + "".join(path(f"M128 {y}h501", DIM, 0.7, opacity=0.7) for y in range(105, 270, 26))
        + path(
            "M126 220h58l16-23h30l13-71 19 107 23-70 18 24h54"
            "l19-50 18 79 24-26h31l20-50 24 69 19-33h108",
            COPPER,
            3,
        )
        + path("M128 237h165l21-22h90l20-14h196", TEAL, 2)
        + circle(376, 137, 6, COPPER, "#201911")
        + label(394, 120, "STEP TRACE")
        + marks(126, 286, 30)
    )


def artifact_rack():
    return (
        box(137, 62, 483, 232, DIM, "none", 5)
        + plate(176, 95, 331, 27, 30)
        + plate(176, 163, 331, 27, 30, TEAL)
        + plate(176, 230, 331, 27, 30)
        + label(236, 143, "BUNDLE")
        + label(236, 211, "CHECKSUM")
        + label(236, 279, "RECEIPT")
        + path("M158 74v208m438-208v208", DIM, 2)
        + flange(565, 187, 22, TEAL)
    )


def branches():
    paths = (
        path("M122 226h110q36 0 65-41l26-37q22-31 58-31h225", TEAL, 3)
        + path("M122 226h485", COPPER, 3)
        + path("M315 226q47 0 81-28l33-29q22-20 57-20h115", DIM, 2)
        + path("M454 117V66h113", TEAL, 2)
    )
    nodes = [
        (140, 226),
        (230, 226),
        (338, 226),
        (448, 226),
        (571, 226),
        (381, 117),
        (454, 117),
        (606, 117),
        (566, 66),
    ]
    return (
        paths
        + "".join(circle(x, y, 8, COPPER if y == 226 else TEAL, "#101b1b") for x, y in nodes)
        + label(145, 252, "DEFAULT BRANCH")
        + label(512, 98, "REVIEW")
    )


def configuration():
    return (
        plate(157, 82, 387, 111, 31)
        + plate(231, 119, 226, 54, 12, TEAL)
        + path("M301 129l-18 15 28 15m73-30 26 15-18 15m-44-30-16 33", COPPER, 3)
        + pipe("M143 237h136l26 37h176", "teal", 11)
        + flange(145, 237, 16, TEAL)
        + label(375, 250, "TYPED CONFIGURATION")
    )


def schema_gate():
    return (
        path("M109 252V83h542v169", DIM, 3)
        + pipe("M98 177h563", "teal", 21)
        + box(247, 105, 263, 147, COPPER, "#182624", 8)
        + box(272, 127, 213, 103, TEAL, "#111e1d", 7)
        + path("M324 172l35 31 74-65", TEAL, 7)
        + flange(127, 177, 23, TEAL)
        + flange(637, 177, 23, TEAL)
        + label(291, 282, "SCHEMA / RESOURCES / CONNECTORS", COPPER)
    )


def exploded():
    return (
        path("M189 79v189M535 79v189", DIM, 1, opacity=0.8)
        + plate(177, 65, 351, 54, 12)
        + plate(177, 133, 351, 54, 12, TEAL)
        + plate(177, 201, 351, 54, 12)
        + label(255, 92, "TYPED CONFIG")
        + label(255, 160, "CONFIGMAP")
        + label(255, 228, "CRONJOB")
        + path("M601 88h23v168h-23", TEAL)
        + marks(224, 288, 20)
    )


def optics():
    return (
        sheet(144, 83, 242, 168, TEAL)
        + scope(417, 150, 92, COPPER)
        + scope(417, 150, 59)
        + pipe("M482 212l81 63", width=28)
        + rivets(417, 150, 82, 82, 12)
        + path("M387 153l23 22 40-47", TEAL, 4)
        + label(531, 102, "INSPECT")
        + path("M488 119h50v-8", DIM)
    )


def comparator():
    return (
        plate(96, 112, 194, 104, 30, TEAL)
        + plate(431, 73, 179, 104, 30)
        + path("M326 174h67m-13-12 13 12-13 12M429 200h-73m13-12-13 12 13 12", TEAL, 2)
        + label(131, 151, "BASELINE")
        + label(462, 111, "CANDIDATE", COPPER)
        + path("M124 264h467", DIM)
        + marks(124, 263, 29)
    )


def sealed():
    contour = "M380 65l111 43v73q0 64-111 107-111-43-111-107v-73z"
    return (
        box(122, 65, 514, 225, DIM, "none", 12)
        + path(contour, COPPER, 2.4, fill="#172320")
        + '<g transform="translate(76 34) scale(.8)">'
        + path(contour, TEAL, 1.4)
        + "</g>"
        + box(345, 154, 70, 58, COPPER, "#152120", 8)
        + path("M359 154v-14a21 21 0 0 1 42 0v14", COPPER, 4)
        + circle(380, 178, 4, TEAL, TEAL)
        + path("M380 182v10M161 103h75m287 0h76M161 252h75m287 0h76", DIM)
    )


def ledger():
    return (
        "".join(
            box(127 + i * 13, 67 + i * 49, 449 - i * 17, 36, TEAL if i % 2 else COPPER)
            for i in range(5)
        )
        + "".join(
            path(f"M{156 + i * 13} {86 + i * 49}h32m14 0h145m15 0h41", DIM, 2) for i in range(5)
        )
        + path("M624 79v191M613 81h23m-23 48h23m-23 47h23m-23 48h23m-23 46h23", TEAL, 1.1)
        + label(457, 56, "SESSION RECORDS")
    )


def connector_board():
    return (
        box(107, 54, 546, 249, DIM, "url(#surface)", 12)
        + path("M252 109h56l43 66h53l51-66h53M252 240h56l43-65m53 0 51 65h53", TEAL, 2)
        + flange(380, 174, 48)
        + flange(240, 110, 27, TEAL)
        + flange(240, 240, 27, TEAL)
        + flange(520, 110, 27)
        + flange(520, 240, 27)
        + rivets(380, 174, 61, 61, 12, TEAL)
        + label(115, 284, "CONNECTOR INTERFACE")
    )


def receiver():
    return (
        scope(375, 174, 113)
        + circle(375, 174, 78, DIM)
        + circle(375, 174, 46, TEAL)
        + path("M183 232l95-49 97-9 97-78 100-10m-197 88 101 49 122-4", COPPER, 2)
        + "".join(
            circle(x, y, 6, COPPER, "#b47748")
            for x, y in (
                (183, 232),
                (278, 183),
                (375, 174),
                (472, 96),
                (572, 86),
                (476, 223),
                (598, 219),
            )
        )
        + label(118, 259, "SOURCE")
        + label(536, 256, "TRACE")
    )


def inlet():
    return (
        pipe("M133 240h168q57 0 57-51v-37q0-51 50-51h179", width=60)
        + flange(134, 240, 56)
        + flange(590, 101, 52, TEAL)
        + path("M359 91v171m-102-88h204", DIM, 1.2)
        + circle(358, 176, 61, TEAL, "none", 1)
        + label(444, 207, "SOURCE INLET")
    )


def test_bench():
    return (
        plate(116, 232, 484, 46, 14)
        + path("M214 230V96h326v133", DIM, 3)
        + box(242, 73, 275, 74, COPPER, "url(#surface)")
        + "".join(circle(281 + i * 64, 112, 10, TEAL, "#1c302c") for i in range(4))
        + path("M275 146v50h205v-50", TEAL, 2)
        + flange(375, 196, 36)
        + label(418, 264, "TEST BENCH")
    )


def evidence_chain():
    return (
        path("M143 225l146-93 166 44 161-108", TEAL, 3)
        + flange(143, 225, 39, TEAL)
        + flange(289, 132, 50)
        + flange(455, 176, 50, TEAL)
        + flange(615, 68, 33)
        + label(143, 296, "SOURCE → VALIDATION → REVIEW", TEAL)
        + marks(237, 260, 22)
    )


def cutaway():
    return (
        pipe("M99 182h561", "teal", 29)
        + plate(247, 104, 222, 94, 40)
        + path("M277 139h161m-130 22h161", TEAL, 2)
        + circle(361, 175, 59, COPPER, "#1a2420", 1.7)
        + path("M335 175h52m-26-26v52m-18-44 36 36m0-36-36 36", TEAL, 2)
        + flange(104, 182, 38, TEAL)
        + flange(659, 182, 35, TEAL)
        + label(270, 265, "CONNECTOR CUTAWAY")
    )


def seal():
    return (
        sheet(181, 81, 317, 191, TEAL)
        + path("M224 225h190", DIM)
        + scope(488, 200, 79, COPPER)
        + rivets(488, 200, 61, 61, 12)
        + path("M458 200l22 22 40-47", TEAL, 4)
        + label(204, 245, "YAML / SHA-256")
    )


def rollback():
    return (
        pipe("M144 193h473", "teal", 15)
        + path("M614 149c-53-122-331-132-453-8m3-35-5 35 37-7", COPPER, 4)
        + flange(143, 193, 31, TEAL)
        + flange(375, 193, 35)
        + flange(615, 193, 31, TEAL)
        + label(113, 251, "REV 01")
        + label(349, 251, "REV 02", COPPER)
        + label(586, 251, "REV 03")
        + label(315, 68, "RESTORE BASELINE", COPPER)
    )


def mesh():
    return (
        "".join(path(f"M{134 + i * 54} 258l110-164", DIM, 1) for i in range(8))
        + "".join(path(f"M133 {96 + i * 27}h482", DIM, 0.9) for i in range(7))
        + box(129, 86, 501, 186, TEAL, "none", 7)
        + scope(378, 180, 63, COPPER)
        + path("M350 175l24 25 42-47", TEAL, 5)
        + label(144, 294, "ISOLATION PERIMETER")
    )


def lattice():
    return (
        sheet(109, 82, 137, 102, TEAL)
        + sheet(128, 170, 137, 102)
        + path("M247 127h91l63 51m-136 45h78l58-45m0 0h108", TEAL, 3)
        + flange(401, 178, 37)
        + box(506, 116, 132, 124, TEAL, "url(#surface)", 9)
        + path("M530 145h78m-78 25h48m-48 25h69", COPPER, 2)
        + label(506, 265, "CITATION RECORD")
    )


SCENES = (
    manifold,
    source_stack,
    junction,
    raceway,
    oscillograph,
    artifact_rack,
    branches,
    configuration,
    schema_gate,
    exploded,
    optics,
    comparator,
    sealed,
    ledger,
    connector_board,
    receiver,
    inlet,
    test_bench,
    evidence_chain,
    cutaway,
    seal,
    rollback,
    mesh,
    lattice,
)


def artwork(name, title, number, drawing):
    plate_label = name.upper().replace("-", " ")
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 760 340" role="img">
<title>{title}</title>
<defs>
 <radialGradient id="light" cx="57%" cy="49%" r="73%">
  <stop stop-color="#273b36"/><stop offset=".49" stop-color="#182622"/>
  <stop offset="1" stop-color="#151917"/>
 </radialGradient>
 <linearGradient id="copper" x1="0" x2="760" y1="0" y2="340" gradientUnits="userSpaceOnUse">
  <stop stop-color="#4f3125"/><stop offset=".35" stop-color="#a76f48"/>
  <stop offset=".54" stop-color="#f2bc84"/>
  <stop offset=".69" stop-color="#a46741"/><stop offset="1" stop-color="#4d2f22"/>
 </linearGradient>
 <linearGradient id="teal" x1="0" x2="760" y1="0" y2="340" gradientUnits="userSpaceOnUse">
  <stop stop-color="#203d3d"/><stop offset=".48" stop-color="#80bcb0"/>
  <stop offset="1" stop-color="#30534f"/>
 </linearGradient>
 <linearGradient id="surface" x2="100%" y2="100%">
  <stop stop-color="#304841"/><stop offset="1" stop-color="#1c2924"/>
 </linearGradient>
 <pattern id="draft" width="28" height="28" patternUnits="userSpaceOnUse">
  <path d="M28 0H0v28" fill="none" stroke="#8cab9e" stroke-opacity=".17" stroke-width=".8"/>
  <path d="M13 14h2m-1-1v2" stroke="#8cab9e" stroke-opacity=".13" stroke-width=".8"/>
 </pattern>
</defs>
<rect width="760" height="340" fill="url(#light)"/>
<rect width="760" height="340" fill="url(#draft)"/>
<path d="M22 53V22h31m654 0h31v31M22 287v31h31m654 0h31v-31"
      fill="none" stroke="#769188" opacity=".65"/>
{label(39, 36, f"PF / {number:02d}", COPPER)}{label(39, 307, plate_label, "#acc3b7")}
{label(647, 307, "DRAWING", "#acc3b7")}
{drawing}
</svg>"""


def main():
    entries = list(PAGE_ARTWORK.values()) + [
        entry for placements in SECTION_ARTWORK.values() for entry in placements
    ]
    DEST.mkdir(parents=True, exist_ok=True)
    for number, ((name, title), scene) in enumerate(zip(entries, SCENES, strict=True), 1):
        (DEST / f"{name}.svg").write_text(
            artwork(name, title, number, scene()) + "\n", encoding="utf-8", newline="\n"
        )
    print(f"Wrote {len(entries)} original PipeFoundry blueprints")


if __name__ == "__main__":
    main()
