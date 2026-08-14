"""Dependency-free Code 128-B barcode rendering (Piece 26.0).

The app ships no runtime dependencies and must work offline (service worker), so
barcodes are drawn as inline SVG from a hand-rolled Code 128-B encoder rather
than a library. Code set B covers ASCII 32–126, which is all our serials use
(uppercase letters, digits, hyphen). The encoder is validated against the
`python-barcode` package in the test suite; only this stdlib version ships.
"""

# Standard Code 128 element-width patterns, index = symbol value 0..106. Each is
# a run of module widths starting with a bar and alternating bar/space; data
# symbols are 11 modules (6 elements), the Stop symbol (106) is 13 (7 elements).
_PATTERNS = [
    "212222", "222122", "222221", "121223", "121322", "131222", "122213",
    "122312", "132212", "221213", "221312", "231212", "112232", "122132",
    "122231", "113222", "123122", "123221", "223211", "221132", "221231",
    "213212", "223112", "312131", "311222", "321122", "321221", "312212",
    "322112", "322211", "212123", "212321", "232121", "111323", "131123",
    "131321", "112313", "132113", "132311", "211313", "231113", "231311",
    "112133", "112331", "132131", "113123", "113321", "133121", "313121",
    "211331", "231131", "213113", "213311", "213131", "311123", "311321",
    "331121", "312113", "312311", "332111", "314111", "221411", "431111",
    "111224", "111422", "121124", "121421", "141122", "141221", "112214",
    "112412", "122114", "122411", "142112", "142211", "241211", "221114",
    "413111", "241112", "134111", "111242", "121142", "121241", "114212",
    "124112", "124211", "411212", "421112", "421211", "212141", "214121",
    "412121", "111143", "111341", "131141", "114113", "114311", "411113",
    "411311", "113141", "114131", "311141", "411131", "211412", "211214",
    "211232", "2331112",
]
_START_B = 104
_STOP = 106
_QUIET = 10          # quiet-zone modules on each side (Code 128 spec: >= 10)


def code128b_modules(data):
    """Return the barcode as a list of (is_bar, width_in_modules) runs, including
    quiet zones. Raises ValueError on characters outside Code set B."""
    values = []
    for ch in data:
        o = ord(ch)
        if not (32 <= o <= 126):
            raise ValueError(f"character {ch!r} is not encodable in Code 128-B")
        values.append(o - 32)
    codes = [_START_B] + values
    checksum = (_START_B + sum(v * (i + 1) for i, v in enumerate(values))) % 103
    codes += [checksum, _STOP]

    runs = [(False, _QUIET)]     # leading quiet zone (space)
    for code in codes:
        bar = True
        for d in _PATTERNS[code]:
            runs.append((bar, int(d)))
            bar = not bar
    runs.append((False, _QUIET))  # trailing quiet zone
    return runs


def code128b_svg(data, module=2, height=64, show_text=True, font_px=13):
    """Render `data` as a scannable Code 128-B barcode SVG string. `module` is the
    width in px of one module (the narrowest bar); `height` is the bar height."""
    runs = code128b_modules(data)
    total_modules = sum(w for _bar, w in runs)
    width = total_modules * module
    text_h = (font_px + 6) if show_text else 0
    svg_h = height + text_h

    rects, x = [], 0
    for bar, w in runs:
        if bar:
            rects.append(f'<rect x="{x}" y="0" width="{w * module}" '
                         f'height="{height}" fill="#000"/>')
        x += w * module
    label = ""
    if show_text:
        label = (f'<text x="{width / 2}" y="{height + font_px}" '
                 f'text-anchor="middle" font-family="monospace" '
                 f'font-size="{font_px}" fill="#000">{data}</text>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
            f'height="{svg_h}" viewBox="0 0 {width} {svg_h}">'
            f'<rect width="{width}" height="{svg_h}" fill="#fff"/>'
            f'{"".join(rects)}{label}</svg>')
