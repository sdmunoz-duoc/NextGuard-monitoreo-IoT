#!/usr/bin/env python3
"""Convierte el plan maestro, los casos de prueba (.md) y los diagramas (.html) a PDF con Chrome headless.

- docs/01_plan_maestro.pdf : incluye un anexo con los 5 diagramas (SVG tomado de docs/diagramas/*.html), en páginas horizontales.
- docs/02_casos_de_prueba.pdf
- docs/diagramas/*.pdf : un PDF A4 horizontal por diagrama (tema claro, sin barra de navegación)

Requisitos: paquete `markdown` y google-chrome/chromium instalado.
Uso:  python build_pdf.py
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

import markdown

from generar_diagramas import CSS as _CSS

# En papel siempre tema claro: se elimina el bloque prefers-color-scheme:dark
CSS_DIAGRAMAS = re.sub(r"@media \(prefers-color-scheme:dark\)\{.*?\}\}", "", _CSS, flags=re.S)

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "docs"))
DIAGRAMAS = [
    ("arquitectura.html", "Arquitectura bajo prueba"),
    ("flujo_datos.html", "Recorrido de una lectura"),
    ("secuencia_pruebas.html", "Secuencia de las pruebas"),
    ("despliegue_aws.html", "Despliegue en AWS"),
    ("estrategia_niveles.html", "Niveles de prueba"),
]

CSS_DOC = """
@page{size:A4;margin:16mm 15mm}
@page wide{size:A4 landscape;margin:12mm}
html{font-size:10.5pt}
body{background:#fff;color:#1c232b;font-family:"Noto Sans","DejaVu Sans",system-ui,sans-serif;line-height:1.5}
main{max-width:none;padding:0}
h1{font-size:20pt;margin:0 0 4pt}h2{font-size:14pt;margin:18pt 0 6pt;border-bottom:1px solid #c8ced6;padding-bottom:3pt;break-after:avoid}
h3{font-size:11.5pt;margin:12pt 0 4pt;break-after:avoid}
table{border-collapse:collapse;width:100%;margin:8pt 0;font-size:9pt;break-inside:auto}
th,td{border:1px solid #c8ced6;padding:3pt 5pt;text-align:left;vertical-align:top}
th{background:#eef1f5}tr{break-inside:avoid}
pre{background:#f1f3f6;padding:7pt;border-radius:4pt;font-size:8.2pt;overflow:hidden;white-space:pre-wrap;break-inside:avoid}
code{font-family:"DejaVu Sans Mono",monospace;font-size:8.6pt;background:#f1f3f6;padding:0 2pt;border-radius:2pt}
pre code{background:none;padding:0}
blockquote{margin:8pt 0;padding:4pt 10pt;border-left:3px solid #0b6bcb;background:#f4f8fd;color:#334}
hr{border:0;border-top:1px solid #c8ced6;margin:12pt 0}
ul,ol{padding-left:16pt}
.anexo{page:wide;break-before:page}
.anexo h2{margin-top:0}
.anexo svg{display:block;width:100%;max-height:148mm;height:auto}
"""


def chrome() -> str:
    for c in ("google-chrome", "chromium", "chromium-browser", "google-chrome-stable"):
        if shutil.which(c):
            return c
    sys.exit("No se encontró Chrome/Chromium")


def a_pdf(html_path: str, pdf_path: str):
    subprocess.run([chrome(), "--headless=new", "--no-sandbox", "--disable-gpu", "--no-pdf-header-footer",
                    f"--print-to-pdf={pdf_path}", f"file://{html_path}"],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=180)


def md_a_html(md_texto: str, titulo: str, anexo: str = "") -> str:
    cuerpo = markdown.markdown(md_texto, extensions=["tables", "fenced_code", "sane_lists"])
    return (f'<!doctype html><html lang="es"><head><meta charset="utf-8"><title>{titulo}</title>'
            f"<style>{CSS_DIAGRAMAS}\n{CSS_DOC}</style></head><body><main>{cuerpo}{anexo}</main></body></html>")


def anexo_diagramas() -> str:
    partes = []
    for n, (archivo, titulo) in enumerate(DIAGRAMAS, 1):
        txt = open(os.path.join(RAIZ, "diagramas", archivo), encoding="utf-8").read()
        svg = re.search(r"<svg.*?</svg>", txt, re.S).group(0)
        cap = re.search(r"<figcaption>(.*?)</figcaption>", txt, re.S).group(1)
        partes.append(f'<section class="anexo"><h2>Anexo A.{n} · {titulo}</h2>{svg}<p style="font-size:9pt;color:#555">{cap}</p></section>')
    return "".join(partes)


def construir(nombre_md: str, anexo: str = ""):
    ruta_md = os.path.join(RAIZ, nombre_md)
    texto = open(ruta_md, encoding="utf-8").read()
    titulo = texto.splitlines()[0].lstrip("# ").strip()
    with tempfile.TemporaryDirectory() as tmp:
        h = os.path.join(tmp, "doc.html")
        open(h, "w", encoding="utf-8").write(md_a_html(texto, titulo, anexo))
        pdf = os.path.join(RAIZ, nombre_md.replace(".md", ".pdf"))
        a_pdf(h, pdf)
    print("PDF:", pdf)


def exportar_diagramas():
    """Un PDF de una sola página por cada diagramas/*.html (horizontal si el SVG es ancho, vertical si es alto)."""
    carpeta = os.path.join(RAIZ, "diagramas")
    for nombre in sorted(os.listdir(carpeta)):
        if not nombre.endswith(".html"):
            continue
        txt = open(os.path.join(carpeta, nombre), encoding="utf-8").read()
        txt = re.sub(r"@media \(prefers-color-scheme:dark\)\{.*?\}\}", "", txt, flags=re.S)
        vb = re.search(r'viewBox="[\d.]+ ([\d.]+) ([\d.]+) ([\d.]+)"', txt)
        ancho, alto = (float(vb.group(2)), float(vb.group(3))) if vb else (1.0, 0.0)
        horizontal = alto == 0 or ancho / alto >= 1.3
        pagina = "A4 landscape" if horizontal else "A4"
        alto_svg = "125mm" if horizontal else "185mm"
        ajuste = (f"<style>@page{{size:{pagina};margin:8mm}}nav{{display:none}}body{{background:#fff;font-size:12px}}"
                  f"main{{max-width:none;padding:0}}.fig{{overflow:visible;border:0;padding:0}}"
                  f".fig svg{{min-width:0;max-height:{alto_svg};margin:0 auto}}"
                  "h1{font-size:16pt;margin:0 0 2px}p.lead{margin:0 0 6px;font-size:9pt}"
                  "ul.notes{margin:8px 0 0;font-size:8.5pt}ul.notes li{margin:2px 0}"
                  "figcaption{font-size:8.5pt;margin:4px 0 0}</style>")
        with tempfile.TemporaryDirectory() as tmp:
            h = os.path.join(tmp, nombre)
            open(h, "w", encoding="utf-8").write(txt.replace("</head>", ajuste + "</head>"))
            pdf = os.path.join(carpeta, nombre.replace(".html", ".pdf"))
            a_pdf(h, pdf)
        print("PDF:", pdf)


if __name__ == "__main__":
    construir("01_plan_maestro.md", anexo_diagramas())
    construir("02_casos_de_prueba.md")
    exportar_diagramas()
