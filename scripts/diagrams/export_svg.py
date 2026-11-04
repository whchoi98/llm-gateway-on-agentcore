"""SVG export per aws-diagram-design references/export.md (diagram-only, fonts via local() then docs/fonts/)."""
import pathlib, re, sys
import xml.etree.ElementTree as ET

src = pathlib.Path(sys.argv[1])
html = src.read_text()
lang = sys.argv[2]
names = [f"architecture.{lang}", f"request-flow.{lang}", f"fallback-sequence.{lang}", f"deploy-order.{lang}"]
fonts = [("Amazon Ember", 400, "normal", "local('Amazon Ember')", "AmazonEmber_W_Rg"),
         ("Amazon Ember", 400, "italic", "local('Amazon Ember Italic'), local('Amazon Ember')", "AmazonEmber_W_RgIt"),
         ("Amazon Ember", 600, "normal", "local('Amazon Ember Medium'), local('Amazon Ember')", "AmazonEmber_W_SBd"),
         ("Amazon Ember", 700, "normal", "local('Amazon Ember Bold'), local('Amazon Ember')", "AmazonEmber_W_Bd"),
         ("Amazon Ember Mono", 400, "normal", "local('Amazon Ember Mono')", "AmazonEmberMono_W_Rg"),
         ("Amazon Ember Mono", 700, "normal", "local('Amazon Ember Mono Bold'), local('Amazon Ember Mono')", "AmazonEmberMono_W_Bd")]
style = "<style>" + "".join(
    f"@font-face {{ font-family: '{fam}'; font-weight: {w}; font-style: {st}; src: {loc}, url('fonts/{f}.woff2') format('woff2'); }}"
    for fam, w, st, loc, f in fonts) + "</style>"
svgs = re.findall(r"<svg\b.*?</svg>", html, flags=re.S)
assert len(svgs) == len(names), len(svgs)
for name, svg in zip(names, svgs):
    assert 'xmlns="http://www.w3.org/2000/svg"' in svg and "viewBox=" in svg
    assert svg.count("<defs>") == 1
    svg = svg.replace("<defs>", "<defs>" + style, 1)  # merge into the existing defs
    out = src.parent / f"{name}.svg"
    out.write_text('<?xml version="1.0" encoding="UTF-8"?>\n' + svg + "\n")
    ET.parse(out)  # strict XML check
    print("wrote", out, out.stat().st_size, "bytes (well-formed XML)")
