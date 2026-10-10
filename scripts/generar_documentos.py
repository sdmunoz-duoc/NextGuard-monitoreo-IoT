#!/usr/bin/env python3
"""Genera a partir de casos_de_prueba.py:  02_casos_de_prueba.md, casos_de_prueba.csv, casos_de_prueba.xlsx

Uso:  python generar_documentos.py            (escribe en la carpeta padre de scripts/)
"""
import csv
import os
from collections import Counter, defaultdict

from openpyxl import Workbook
from openpyxl.formatting.rule import CellIsRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from casos_de_prueba import NIVELES, REQUISITOS, casos

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "docs"))
TIPOS = {"A": "Automatizado (pytest)", "M": "Manual", "S": "Semi-automático"}
ESTADOS = ["Pendiente", "En curso", "Pasó", "Falló", "Bloqueado", "No aplica"]
COLUMNAS = [  # (clave, encabezado, ancho)
    ("id", "ID", 12), ("nivel", "Nivel", 7), ("componente", "Componente", 22), ("titulo", "Título", 42),
    ("requisito", "Requisito", 10), ("prioridad", "Prioridad", 10), ("tipo", "Tipo", 6),
    ("precondiciones", "Precondiciones", 38), ("pasos", "Pasos", 55), ("datos", "Datos de prueba", 24),
    ("esperado", "Resultado esperado", 48), ("automatizacion", "Automatización / referencia", 40),
    ("estado", "Estado", 12), ("resultado_real", "Resultado real", 32), ("fecha", "Fecha", 12),
    ("ejecutor", "Ejecutor", 14), ("evidencia", "Evidencia (captura/log)", 26),
]


def escribir_csv(cs):
    with open(os.path.join(RAIZ, "casos_de_prueba.csv"), "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow([h for _, h, _ in COLUMNAS])
        for c in cs:
            w.writerow([c[k].replace("\n", " | ") if isinstance(c[k], str) else c[k] for k, _, _ in COLUMNAS])


def escribir_md(cs):
    por_nivel = defaultdict(list)
    for c in cs:
        por_nivel[c["id"].split("-")[1]].append(c)
    tipos = Counter(c["tipo"] for c in cs)

    L = ["# Casos de prueba de integración", "",
         "> Generado desde `scripts/casos_de_prueba.py` (fuente única). Para registrar resultados usa "
         "`casos_de_prueba.xlsx` (columnas *Estado*, *Resultado real*, *Evidencia*).", "",
         f"**Total:** {len(cs)} casos — {tipos['A']} automatizados (pytest), {tipos['S']} semi-automáticos, {tipos['M']} manuales.", "",
         "**Tipo:** A = automatizado · S = semi-automático (script/simulador + revisión) · M = manual. "
         "**Prioridad:** Alta = bloquea la aceptación; Media = debe cumplirse; Baja = deseable.", "",
         "## Resumen por nivel", "", "| Nivel | Componente | Casos | Alta | A | S | M |", "|---|---|---|---|---|---|---|"]
    for cod, (niv, nombre) in NIVELES.items():
        g = por_nivel[cod]
        L.append(f"| {niv} | {nombre} | {len(g)} | {sum(c['prioridad'] == 'Alta' for c in g)} | "
                 f"{sum(c['tipo'] == 'A' for c in g)} | {sum(c['tipo'] == 'S' for c in g)} | {sum(c['tipo'] == 'M' for c in g)} |")

    L += ["", "## Requisitos y trazabilidad", "", "| Requisito | Descripción | Casos |", "|---|---|---|"]
    for rid, desc in REQUISITOS:
        ids = ", ".join(c["id"] for c in cs if c["requisito"] == rid)
        L.append(f"| {rid} | {desc} | {ids} |")

    for cod, (niv, nombre) in NIVELES.items():
        L += ["", f"## {niv} — {nombre}", ""]
        for c in por_nivel[cod]:
            L += [f"### {c['id']} — {c['titulo']}", "",
                  f"- **Requisito:** {c['requisito']} · **Prioridad:** {c['prioridad']} · **Tipo:** {TIPOS[c['tipo']]}",
                  f"- **Precondiciones:** {c['precondiciones']}",
                  "- **Pasos:**"]
            L += [f"  {p}" for p in c["pasos"].split("\n")]
            L += [f"- **Datos:** {c['datos']}",
                  f"- **Resultado esperado:** {c['esperado']}"]
            if c["automatizacion"]:
                L.append(f"- **Automatización:** `{c['automatizacion']}`")
            L.append("")
    with open(os.path.join(RAIZ, "02_casos_de_prueba.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")


def escribir_xlsx(cs):
    wb = Workbook()
    borde = Border(*[Side(style="thin", color="BFBFBF")] * 4)
    cab = PatternFill("solid", fgColor="1F3A5F")

    # --- Hoja Casos ---
    ws = wb.active
    ws.title = "Casos"
    for j, (_, h, w) in enumerate(COLUMNAS, 1):
        c = ws.cell(row=1, column=j, value=h)
        c.font, c.fill = Font(bold=True, color="FFFFFF"), cab
        c.alignment = Alignment(wrap_text=True, vertical="center")
        ws.column_dimensions[get_column_letter(j)].width = w
    for i, caso in enumerate(cs, 2):
        for j, (k, _, _) in enumerate(COLUMNAS, 1):
            c = ws.cell(row=i, column=j, value=caso[k])
            c.alignment, c.border = Alignment(wrap_text=True, vertical="top"), borde
    ultima = len(cs) + 1
    ws.freeze_panes = "E2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(COLUMNAS))}{ultima}"
    col_estado = [k for k, _, _ in COLUMNAS].index("estado") + 1
    L = get_column_letter(col_estado)
    dv = DataValidation(type="list", formula1='"' + ",".join(ESTADOS) + '"', allow_blank=False)
    ws.add_data_validation(dv)
    dv.add(f"{L}2:{L}{ultima}")
    for texto, color in (("Pasó", "C6EFCE"), ("Falló", "FFC7CE"), ("En curso", "FFEB9C"), ("Bloqueado", "F4B183")):
        ws.conditional_formatting.add(f"{L}2:{L}{ultima}",
                                      CellIsRule(operator="equal", formula=[f'"{texto}"'], fill=PatternFill("solid", bgColor=color)))

    # --- Hoja Resumen (fórmulas que se calculan al abrir) ---
    rs = wb.create_sheet("Resumen")
    rs.append(["Nivel", "Componente", "Total"] + ESTADOS + ["% Pasó"])
    for c in rs[1]:
        c.font, c.fill = Font(bold=True, color="FFFFFF"), cab
    rango_n, rango_e = f"Casos!$B$2:$B${ultima}", f"Casos!${L}$2:${L}${ultima}"
    niveles = list(dict.fromkeys(v[0] for v in NIVELES.values()))
    for r, niv in enumerate(niveles, 2):
        nombre = " / ".join(v[1] for v in NIVELES.values() if v[0] == niv)
        fila = [niv, nombre, f'=COUNTIF({rango_n},A{r})']
        for k in range(len(ESTADOS)):
            fila.append(f'=COUNTIFS({rango_n},$A{r},{rango_e},{get_column_letter(4 + k)}$1)')
        fila.append(f'=IF(C{r}=0,0,{get_column_letter(4 + ESTADOS.index("Pasó"))}{r}/C{r})')
        rs.append(fila)
    t = len(niveles) + 2
    fila_t = ["TOTAL", "", f"=SUM(C2:C{t - 1})"] + [f"=SUM({get_column_letter(4 + k)}2:{get_column_letter(4 + k)}{t - 1})" for k in range(len(ESTADOS))]
    fila_t.append(f'=IF(C{t}=0,0,{get_column_letter(4 + ESTADOS.index("Pasó"))}{t}/C{t})')
    rs.append(fila_t)
    for c in rs[t]:
        c.font = Font(bold=True)
    for r in range(2, t + 1):
        rs.cell(row=r, column=4 + len(ESTADOS)).number_format = "0%"
    rs.column_dimensions["A"].width, rs.column_dimensions["B"].width = 10, 42

    # --- Hoja Trazabilidad ---
    tr = wb.create_sheet("Trazabilidad")
    tr.append(["Requisito", "Descripción", "N.º casos", "Casos"])
    for c in tr[1]:
        c.font, c.fill = Font(bold=True, color="FFFFFF"), cab
    for rid, desc in REQUISITOS:
        ids = [c["id"] for c in cs if c["requisito"] == rid]
        tr.append([rid, desc, len(ids), ", ".join(ids)])
    for col, w in zip("ABCD", (11, 70, 10, 90)):
        tr.column_dimensions[col].width = w
    for row in tr.iter_rows(min_row=2):
        for c in row:
            c.alignment = Alignment(wrap_text=True, vertical="top")

    # --- Hoja Instrucciones ---
    ins = wb.create_sheet("Instrucciones")
    for linea in ["Cómo usar esta matriz",
                  "1. Trabaja en la hoja 'Casos'. Actualiza Estado (lista desplegable), Resultado real, Fecha, Ejecutor y Evidencia.",
                  "2. La hoja 'Resumen' se recalcula sola (fórmulas COUNTIFS).",
                  "3. Tipo: A = automatizado con pytest, S = semi-automático (script/simulador), M = manual.",
                  "4. Un caso 'Falló' debe tener evidencia (captura del monitor serie, log de la API o consulta SQL).",
                  "5. La fuente de los casos es scripts/casos_de_prueba.py; si cambias el plan, regenera con generar_documentos.py."]:
        ins.append([linea])
    ins["A1"].font = Font(bold=True, size=13)
    ins.column_dimensions["A"].width = 120
    wb.move_sheet("Instrucciones", offset=-3)
    wb.save(os.path.join(RAIZ, "casos_de_prueba.xlsx"))


if __name__ == "__main__":
    cs = casos()
    escribir_csv(cs)
    escribir_md(cs)
    escribir_xlsx(cs)
    print(f"Generados {len(cs)} casos en {RAIZ}")
