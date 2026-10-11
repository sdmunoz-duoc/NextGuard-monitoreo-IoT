#!/usr/bin/env python3
"""Genera diagramas/*.html (SVG inline, autocontenidos, tema claro/oscuro).

Uso:  python generar_diagramas.py
Los conteos de casos por nivel salen de casos_de_prueba.py.
"""
import html
import os
from collections import Counter

from casos_de_prueba import NIVELES, casos

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "docs"))
SALIDA = os.path.join(RAIZ, "diagramas")


def esc(s):
    return html.escape(s, quote=False)


# ---------------------------------------------------------------- mini DSL SVG
class Svg:
    def __init__(self, w, h, label, y0=0):
        self.w, self.h, self.label, self.y0, self.p = w, h, label, y0, []

    def rect(self, x, y, w, h, cls="box", rx=8):
        self.p.append(f'<rect class="{cls}" x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}"/>')

    def text(self, x, y, s, cls="t", anchor="middle"):
        self.p.append(f'<text class="{cls}" x="{x}" y="{y}" text-anchor="{anchor}">{esc(s)}</text>')

    def box(self, x, y, w, h, title, subs=(), cls="box"):
        self.rect(x, y, w, h, cls)
        total = 15 + 15 * len(subs)
        y0 = y + (h - total) / 2 + 12
        self.text(x + w / 2, y0, title, "tb")
        for i, s in enumerate(subs):
            self.text(x + w / 2, y0 + 17 + i * 15, s, "ts")

    def line(self, pts, kind="", arrow=True, dash=False):
        """kind: '', 'ok', 'bad', 'warn', 'acc'"""
        cls = "edge" + (f" e-{kind}" if kind else "") + (" dash" if dash else "")
        mk = f' marker-end="url(#a{"-" + kind if kind else ""})"' if arrow else ""
        d = " ".join(f"{x},{y}" for x, y in pts)
        self.p.append(f'<polyline class="{cls}" points="{d}"{mk}/>')

    def badge(self, x, y, s, kind="acc"):
        self.p.append(f'<circle class="badge b-{kind}" cx="{x}" cy="{y}" r="15"/>')
        self.text(x, y + 4, s, "tbadge")

    def cross(self, x, y):
        self.p.append(f'<circle class="badge b-bad" cx="{x}" cy="{y}" r="10"/>')
        self.p.append(f'<path class="xmark" d="M{x - 4},{y - 4} L{x + 4},{y + 4} M{x + 4},{y - 4} L{x - 4},{y + 4}"/>')

    def render(self):
        marks = "".join(
            f'<marker id="a{"-" + k if k else ""}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" '
            f'markerHeight="7" orient="auto"><path class="mk{" mk-" + k if k else ""}" d="M0,0 L10,5 L0,10 z"/></marker>'
            for k in ("", "ok", "bad", "warn", "acc")
        )
        return (f'<svg viewBox="0 {self.y0} {self.w} {self.h - self.y0}" xmlns="http://www.w3.org/2000/svg" role="img" '
                f'aria-label="{html.escape(self.label)}"><defs>{marks}</defs>' + "".join(self.p) + "</svg>")


# ---------------------------------------------------------------- página
CSS = """
:root{--bg:#f7f7f4;--fg:#1c232b;--muted:#5a6673;--line:#c8ced6;--box:#ffffff;--zone:#eef1f5;
--acc:#0b6bcb;--acc-soft:#dcebfb;--ok:#1a7f4b;--warn:#a85a00;--bad:#b42318;color-scheme:light}
@media (prefers-color-scheme:dark){:root{--bg:#12161b;--fg:#e6eaee;--muted:#9aa6b2;--line:#3a444f;--box:#1b2129;
--zone:#171c22;--acc:#5aa9ff;--acc-soft:#1c3552;--ok:#4cc38a;--warn:#f0a35e;--bad:#ff7b72;color-scheme:dark}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:1120px;margin:0 auto;padding:24px 16px 48px}
nav{font-size:14px;margin-bottom:18px;display:flex;flex-wrap:wrap;gap:6px 16px}
nav a{color:var(--acc);text-decoration:none}nav a:hover{text-decoration:underline}
nav a[aria-current]{color:var(--fg);font-weight:600;text-decoration:none}
h1{font-size:1.5rem;line-height:1.25;margin:0 0 6px}
p.lead{color:var(--muted);margin:0 0 20px;max-width:75ch}
figure{margin:0}
.fig{overflow-x:auto;border:1px solid var(--line);border-radius:10px;background:var(--box);padding:8px}
.fig svg{display:block;width:100%;min-width:760px;height:auto}
figcaption{color:var(--muted);font-size:14px;margin:10px 2px 0;max-width:85ch}
ul.notes{margin:20px 0 0;padding-left:20px;max-width:85ch}ul.notes li{margin:6px 0}
code{font:0.9em ui-monospace,Menlo,Consolas,monospace;background:var(--zone);padding:1px 5px;border-radius:4px}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:14px;margin-top:8px}
.card{display:block;border:1px solid var(--line);border-radius:10px;padding:14px 16px;background:var(--box);color:inherit;text-decoration:none}
.card:hover{border-color:var(--acc)}.card h2{font-size:1.05rem;margin:0 0 4px;color:var(--acc)}
.card p{margin:0;color:var(--muted);font-size:14px}
/* SVG */
svg text{font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
.box{fill:var(--box);stroke:var(--fg);stroke-width:1.4}
.box.acc{stroke:var(--acc);stroke-width:2}.box.tool{stroke:var(--muted);stroke-dasharray:5 3}
.f-ok{fill:var(--box);stroke:var(--ok);stroke-width:1.6;stroke-dasharray:6 4}
.f-warn{fill:var(--box);stroke:var(--warn);stroke-width:1.6;stroke-dasharray:6 4}
.f-bad{fill:var(--box);stroke:var(--bad);stroke-width:1.6;stroke-dasharray:6 4}
.zone{fill:var(--zone);stroke:var(--line);stroke-width:1.4;stroke-dasharray:7 4}
.sg{fill:none;stroke:var(--muted);stroke-width:1.2;stroke-dasharray:3 3}
.bar{fill:var(--acc-soft);stroke:var(--acc);stroke-width:1.5}.bar.soft{fill:none;stroke-dasharray:6 4}
.guide{stroke:var(--line);stroke-width:1;stroke-dasharray:2 4}
.edge{fill:none;stroke:var(--fg);stroke-width:1.6}.edge.dash{stroke-dasharray:6 4}.plain{fill:none;stroke:var(--muted);stroke-width:1.2}
.e-ok{stroke:var(--ok)}.e-bad{stroke:var(--bad)}.e-warn{stroke:var(--warn)}.e-acc{stroke:var(--acc)}
.mk{fill:var(--fg)}.mk-ok{fill:var(--ok)}.mk-bad{fill:var(--bad)}.mk-warn{fill:var(--warn)}.mk-acc{fill:var(--acc)}
.life{stroke:var(--line);stroke-width:1.2;stroke-dasharray:4 4}
.frame{fill:none;stroke:var(--line);stroke-width:1.2}.tab{fill:var(--zone);stroke:var(--line);stroke-width:1.2}
.badge{stroke-width:1.6}.b-acc{fill:var(--acc);stroke:var(--acc)}.b-bad{fill:var(--bad);stroke:var(--bad)}
.b-ok{fill:var(--ok);stroke:var(--ok)}.b-warn{fill:var(--warn);stroke:var(--warn)}
.xmark{stroke:#fff;stroke-width:2;fill:none;stroke-linecap:round}
.t{fill:var(--fg);font-size:12px}.tb{fill:var(--fg);font-size:13px;font-weight:600}.ts{fill:var(--muted);font-size:11px}
.tz{fill:var(--muted);font-size:11px;font-weight:700;letter-spacing:.06em}.tm{fill:var(--muted);font-size:11px;font-family:ui-monospace,Menlo,Consolas,monospace}
.tbadge{fill:#fff;font-size:11px;font-weight:700}.tk-ok{fill:var(--ok);font-size:11px;font-weight:700;letter-spacing:.05em}
.tk-warn{fill:var(--warn);font-size:11px;font-weight:700;letter-spacing:.05em}.tk-bad{fill:var(--bad);font-size:11px;font-weight:700;letter-spacing:.05em}
.tacc{fill:var(--acc);font-size:12px;font-weight:600}.tbad{fill:var(--bad);font-size:12px;font-weight:600}.tokk{fill:var(--ok);font-size:12px;font-weight:600}
"""

NAV = [("index.html", "Índice"), ("arquitectura.html", "Arquitectura"), ("flujo_datos.html", "Flujo de datos"),
       ("secuencia_pruebas.html", "Secuencia"), ("despliegue_aws.html", "Despliegue AWS"), ("estrategia_niveles.html", "Niveles")]


def pagina(archivo, titulo, lead, svg, caption, notas):
    nav = "".join(f'<a href="{h}"{" aria-current=page" if h == archivo else ""}>{esc(t)}</a>' for h, t in NAV)
    li = "".join(f"<li>{n}</li>" for n in notas)
    doc = f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light dark"><title>{esc(titulo)}</title><style>{CSS}</style></head>
<body><main><nav>{nav}</nav><h1>{esc(titulo)}</h1><p class="lead">{lead}</p>
<figure><div class="fig">{svg}</div><figcaption>{caption}</figcaption></figure>
<ul class="notes">{li}</ul></main></body></html>
"""
    with open(os.path.join(SALIDA, archivo), "w", encoding="utf-8") as f:
        f.write(doc)


# ---------------------------------------------------------------- 1. arquitectura
def arquitectura():
    s = Svg(1060, 470, "Arquitectura: el ESP32 con sensor DHT llega por WiFi e Internet a la API, que guarda en PostgreSQL; "
                       "API, base de datos y Grafana son contenedores Docker de una sola EC2; PostgreSQL no es accesible desde Internet", y0=34)
    s.rect(16, 50, 328, 360, "zone")
    s.text(30, 72, "LABORATORIO · WiFi 2.4 GHz", "tz", "start")
    s.rect(530, 50, 514, 360, "zone")
    s.text(546, 72, "AWS LEARNER LAB · VPC", "tz", "start")
    s.rect(538, 86, 494, 304, "sg")
    s.text(552, 104, "EC2 · t3.medium · docker compose · nextguard-sg", "tz", "start")

    s.box(36, 140, 100, 60, "Sensor DHT", ["11 / 22"])
    s.box(180, 140, 130, 60, "ESP32", ["cola · NTP · reintentos"], "box acc")
    s.line([(136, 170), (180, 170)])
    s.text(158, 162, "GPIO", "ts")
    s.box(180, 260, 130, 50, "Router WiFi", ["WPA2"])
    s.line([(245, 200), (245, 260)])
    s.text(255, 234, "WiFi", "ts", "start")

    s.box(390, 86, 110, 44, "pool.ntp.org")
    s.line([(245, 140), (245, 108), (390, 108)], "acc", dash=True)
    s.text(318, 100, "hora NTP · UDP 123", "ts")

    s.box(390, 160, 110, 46, "Simulador", ["(PC) · pytest"], "box tool")
    s.line([(445, 206), (445, 235)], "acc", dash=True)
    s.text(453, 226, "mismo POST", "ts", "start")

    s.box(390, 235, 110, 100, "Internet")
    s.line([(310, 285), (390, 285)])
    s.text(350, 277, "HTTP", "ts")

    s.box(604, 235, 140, 100, "api · FastAPI", ["TCP 8000", "valida · autentica", "idempotencia por seq"], "box acc")
    s.line([(500, 290), (604, 290)])
    s.text(571, 276, "POST JSON", "ts")
    s.text(571, 308, "X-API-Key", "ts")

    s.box(876, 235, 144, 100, "db · PostgreSQL 16", ["solo red interna", "volumen pgdata", "UNIQUE(disp., seq)"], "box acc")
    s.line([(744, 285), (876, 285)])
    s.text(810, 277, "SQL", "ts")

    s.box(716, 110, 170, 70, "grafana", ["TCP 3000", "dashboards"], "box acc")
    s.line([(500, 248), (520, 248), (520, 145), (716, 145)])
    s.text(618, 137, "navegador · HTTP 3000", "ts")
    s.line([(886, 145), (948, 145), (948, 235)], "ok")
    s.text(940, 200, "SQL (grafana_ro)", "ts", "end")

    # acceso público a PostgreSQL: bloqueado
    s.line([(420, 335), (420, 372), (858, 372)], "bad", arrow=False, dash=True)
    s.cross(872, 372)
    s.text(640, 364, "TCP 5432 desde Internet: descartado (IT-SEC-06)", "tbad")

    s.badge(158, 222, "N1")
    s.badge(350, 320, "N2")
    s.badge(806, 322, "N3")
    s.badge(1020, 72, "N0")
    s.badge(40, 440, "N4")
    s.line([(62, 440), (990, 440)], "acc")
    s.text(526, 432, "extremo a extremo: sensor → BD → consulta GET /lecturas y panel de Grafana", "tacc")

    pagina("arquitectura.html", "Arquitectura bajo prueba",
           "Quién habla con quién, por dónde cruza la red y qué tramo cubre cada nivel de prueba.",
           s.render(),
           "El ESP32 solo conoce a la API; la API es el único componente que escribe en PostgreSQL y Grafana solo lo lee, con un usuario de solo lectura. "
           "Los tres servicios son contenedores de una misma EC2. El simulador reemplaza al ESP32 con el mismo POST, y la línea roja muestra el camino que "
           "<strong>debe fallar</strong>: PostgreSQL no publica su puerto.",
           ["<strong>N1</strong> sensor↔ESP32 · <strong>N2</strong> ESP32↔red/API · <strong>N3</strong> API↔BD · "
            "<strong>N4</strong> recorre todo el camino · <strong>N0</strong> verifica el entorno AWS y el stack Docker · N5/N6 se aplican sobre todo el conjunto.",
            "La hora llega por NTP directamente a Internet, no pasa por la API: si falla, la lectura se guarda con <code>ts_dispositivo = null</code>.",
            "Sin Elastic IP, la dirección de la EC2 cambia al reiniciar y el firmware debe actualizarse (riesgo R-01)."])


# ---------------------------------------------------------------- 2. flujo de datos
def flujo_datos():
    W, H = 1080, 760
    s = Svg(W, H, "Recorrido de una lectura en siete pasos, con lo que ocurre en cada fallo posible: se absorbe, se degrada o se pierde una muestra")
    filas = [
        ("Lectura del sensor", "DHT · cada 10 s", None,
         ("warn", "SE DEGRADA", ["NaN → la muestra se omite"], "sin dato / NaN", ["IT-SEN-02"])),
        ("Asignar seq y hora", "seq en NVS · hora NTP", "T y H válidas",
         ("warn", "SE DEGRADA", ["Sin NTP → ts_dispositivo = null", "Reinicio → el seq salta +20"], "sin NTP / reinicio", ["IT-NET-04", "IT-E2E-03"])),
        ("Cola en RAM", "60 muestras, FIFO", "muestra {seq, hora, T, H}",
         ("bad", "SE PIERDE", ["Cola llena → descarta la más antigua", "y suma a «perdidas»"], "sin envío 10 min", ["IT-NFR-08"])),
        ("Envío HTTP", "POST · o /batch si hay varias", "vaciar cola",
         ("ok", "SE ABSORBE", ["Sin WiFi · timeout · 5xx · 401 → conserva", "y reintenta (backoff 2 → 60 s)"], "no llega o no autoriza", ["IT-NET-03 · IT-DB-11", "IT-API-19/20/21"])),
        ("API valida", "clave · esquema · tamaño", "JSON + X-API-Key",
         ("bad", "SE PIERDE", ["422 / 413 → el ESP32 descarta la muestra", "(un lote se reintenta individual)"], "rechazada", ["IT-API-05…10"])),
        ("INSERT en la BD", "UNIQUE (dispositivo, seq)", "válida",
         ("ok", "SE ABSORBE", ["Mismo seq → 200 {duplicado: true}", "no inserta"], "seq repetido", ["IT-API-02", "IT-DB-02"])),
        ("Verificación", "GET /lecturas + simulador --verify", "commit",
         None),
    ]
    x0, bw, bh, paso = 120, 230, 60, 100
    for i, (tit, sub, ent, fallo) in enumerate(filas):
        y = 50 + i * paso
        s.box(x0, y, bw, bh, tit, [sub], "box acc")
        s.badge(30, y + bh / 2, str(i + 1))
        if ent:
            s.line([(x0 + bw / 2, y - 40), (x0 + bw / 2, y)], "acc")
            s.text(x0 + bw / 2 + 10, y - 16, ent, "ts", "start")
        if fallo:
            kind, tag, lineas, edge, casos_ = fallo
            fx = 480
            s.rect(fx, y, 330, bh, f"f-{kind}")
            s.text(fx + 12, y + 20, tag, f"tk-{kind}", "start")
            for k, ln in enumerate(lineas):
                s.text(fx + 12, y + 38 + k * 14, ln, "t", "start")
            s.line([(x0 + bw, y + bh / 2), (fx, y + bh / 2)], kind, dash=True)
            s.text((x0 + bw + fx) / 2, y + bh / 2 - 7, edge, "ts")
            for k, ln in enumerate(casos_):
                s.text(fx + 330 + 14, y + bh / 2 - 2 + k * 14 - (len(casos_) - 1) * 7 + 6, ln, "tm", "start")

    # bucle de reintento: del envío (fila 4) de vuelta a la cola (fila 3)
    y3, y4 = 50 + 2 * paso + 30, 50 + 3 * paso + 30
    s.line([(x0, y4), (72, y4), (72, y3), (x0, y3)], "warn", dash=True)
    s.p.append(f'<text class="ts" transform="translate(64,{(y3 + y4) / 2}) rotate(-90)" text-anchor="middle">reintento</text>')
    pagina("flujo_datos.html", "Recorrido de una lectura",
           "Los siete pasos que sigue una muestra y qué ocurre con ella cuando algo falla en cada paso.",
           s.render(),
           "Cada recuadro punteado es un fallo inducido en las pruebas. <strong>Se absorbe</strong>: no se pierde nada. "
           "<strong>Se degrada</strong>: la lectura llega con menos información. <strong>Se pierde</strong>: una muestra se descarta y queda contada.",
           ["Los dos únicos puntos donde el diseño acepta perder una muestra son la <strong>cola llena</strong> y el <strong>rechazo 4xx</strong>; "
            "ambos se registran en el monitor serie (<code>perdidas</code>) para poder contrastarlos con la BD.",
            "La idempotencia depende del par (<code>device_id</code>, <code>seq</code>): por eso el <code>seq</code> se guarda en NVS y salta 20 al reiniciar.",
            "El paso 7 es lo que convierte el resultado en evidencia: el simulador compara los <code>seq</code> enviados con los guardados."])


# ---------------------------------------------------------------- 3. secuencia
def secuencia():
    s = Svg(1060, 940, "Diagrama de secuencia de cinco escenarios de prueba entre ESP32, API, base de datos y verificador")
    X = {"esp": 120, "api": 420, "db": 720, "ver": 960}
    nombres = {"esp": ("ESP32", "firmware"), "api": ("api", "FastAPI · contenedor"), "db": ("db", "PostgreSQL · contenedor"), "ver": ("Verificador", "simulador · pytest")}
    for k, (t, sb) in nombres.items():
        s.box(X[k] - 75, 10, 150, 46, t, [sb], "box acc" if k != "ver" else "box tool")
    idx_vida = len(s.p)

    y = [80]

    def marco(titulo, casos_):
        s.rect(20, y[0], 1020, 24, "tab")
        s.text(32, y[0] + 16, titulo, "tb", "start")
        s.text(1028, y[0] + 16, casos_, "tm", "end")
        y[0] += 44

    def fin_marco(alto_ini):
        s.rect(20, alto_ini, 1020, y[0] - alto_ini - 6, "frame")
        y[0] += 14

    def msg(a, b, txt, kind="", dash=False):
        xa, xb = X[a], X[b]
        s.line([(xa, y[0]), (xb + (-2 if xb > xa else 2), y[0])], kind, dash=dash)
        s.text((xa + xb) / 2, y[0] - 6, txt, "t")
        y[0] += 38

    def nota(a, txt, kind="ts"):
        if a == "ver":   # la línea del verificador está al borde derecho: la nota va hacia la izquierda
            s.text(X[a] - 12, y[0] - 8, txt, kind, "end")
        else:
            s.text(X[a] + 12, y[0] - 8, txt, kind, "start")
        y[0] += 26

    # A
    ini = y[0]; marco("A · Camino feliz", "IT-E2E-01 · IT-API-01")
    msg("esp", "api", "POST /lecturas {seq=7, T, H} + X-API-Key")
    msg("api", "db", "SELECT: ¿existe (dispositivo, seq=7)?  → no")
    msg("api", "db", "INSERT lectura + mediciones · COMMIT")
    msg("api", "esp", "201 {duplicado: false}", "ok", True)
    nota("esp", "desencola seq=7", "tokk")
    fin_marco(ini)
    # B
    ini = y[0]; marco("B · La respuesta se perdió y el ESP32 reintenta", "IT-API-02 · IT-DB-02")
    msg("esp", "api", "POST /lecturas {seq=7}  (reintento por timeout)")
    msg("api", "db", "SELECT → ya existe seq=7")
    msg("api", "esp", "200 {duplicado: true}  · no inserta", "ok", True)
    fin_marco(ini)
    # C
    ini = y[0]; marco("C · Clave ausente o incorrecta", "IT-API-03/04 · IT-API-19")
    msg("esp", "api", "POST /lecturas con X-API-Key errónea")
    msg("api", "esp", "401  · sin tocar la BD", "bad", True)
    nota("esp", "conserva la muestra y espera 2 → 4 → 8 … 60 s", "tbad")
    fin_marco(ini)
    # D
    ini = y[0]; marco("D · API o BD caída y recuperación", "IT-API-20 · IT-DB-11 · IT-NET-03")
    msg("esp", "api", "POST /lecturas {seq=8}")
    msg("api", "esp", "sin respuesta (timeout 5 s) o 5xx / 503", "warn", True)
    nota("esp", "encola seq=8…20 mientras dura la caída", "tk-warn")
    msg("esp", "api", "POST /lecturas/batch [seq 8 … 20]   (10 por lote)")
    msg("api", "db", "INSERT × 13 · UNIQUE evita repetidos")
    msg("api", "esp", "200 {insertadas: 13, duplicadas: 0}", "ok", True)
    fin_marco(ini)
    # E
    ini = y[0]; marco("E · Verificación", "IT-E2E-01/02 · simulador --verify")
    msg("ver", "api", "GET /lecturas?device_id=…&limit=1000 + X-API-Key")
    msg("api", "db", "SELECT lecturas + mediciones")
    msg("api", "ver", "200 [lecturas]", "ok", True)
    nota("ver", "compara con los seq enviados: faltan = 0 · duplicadas = 0", "tokk")
    fin_marco(ini)
    s.h = int(y[0] + 10)
    s.p[idx_vida:idx_vida] = [f'<line class="life" x1="{X[k]}" y1="56" x2="{X[k]}" y2="{y[0] - 6}"/>' for k in X]

    pagina("secuencia_pruebas.html", "Secuencia de las pruebas",
           "Cinco escenarios entre el ESP32, la API y PostgreSQL (más el verificador): qué mensajes se cruzan y qué respuesta se espera.",
           s.render(),
           "Las líneas discontinuas son respuestas. Verde = éxito, ámbar = degradación recuperable, rojo = rechazo. "
           "El escenario D es el que justifica la cola en el ESP32 y el endpoint <code>/batch</code>.",
           ["A y B muestran por qué <code>(device_id, seq)</code> es la clave de idempotencia: el reintento recibe 200 y no genera otra fila.",
            "En C la API responde sin consultar la BD; el ESP32 <strong>no descarta</strong> la muestra porque un 401 es un problema de configuración, no del dato.",
            "En D la BD caída se ve igual que la API caída desde el ESP32 (5xx o timeout); <code>/health</code> distingue ambos casos (503 = BD)."])


# ---------------------------------------------------------------- 4. despliegue AWS
def despliegue():
    s = Svg(1060, 510, "Despliegue en AWS Learner Lab: una EC2 con docker compose y tres contenedores; el ESP32 llega al puerto 8000, tu navegador a Grafana en el 3000 y tu PC por SSH; PostgreSQL no publica puertos", y0=34)
    s.box(20, 105, 200, 70, "ESP32", ["en el WiFi del laboratorio"])
    s.box(20, 200, 200, 70, "Tu PC", ["SSH · simulador"])
    s.box(20, 295, 200, 70, "Navegador", ["dashboards de Grafana"])
    s.rect(320, 50, 720, 330, "zone")
    s.text(336, 72, "VPC DEL LABORATORIO · us-east-1 / us-west-2", "tz", "start")
    s.rect(350, 90, 670, 230, "sg")
    s.text(364, 108, "nextguard-sg · EC2 t3.medium (t3.large si se añaden servicios) · Amazon Linux 2023 · docker compose", "tz", "start")

    s.box(372, 130, 190, 100, "api", ["FastAPI · uvicorn", "TCP 8000 · 512 MB"], "box acc")
    s.box(592, 130, 190, 100, "grafana", ["grafana-oss :3000", "datasource PostgreSQL"], "box acc")
    s.box(812, 130, 190, 100, "db", ["postgres:16 · sin puertos", "volumen pgdata"], "box acc")
    s.line([(562, 180), (592, 180)], arrow=False)
    s.line([(782, 180), (812, 180)], arrow=False)
    s.text(710, 262, "red «backend»: api y grafana resuelven db:5432", "ts", "start")
    s.box(372, 270, 190, 44, "Elastic IP", ["asociada a la instancia"], "box")

    s.line([(220, 140), (372, 140)], "ok")
    s.text(290, 132, "TCP 8000", "ts")
    s.line([(220, 235), (350, 235)], "ok")
    s.text(285, 227, "TCP 22", "ts")
    s.text(285, 251, "solo Mi IP", "ts")
    s.line([(220, 335), (687, 335), (687, 230)], "ok")
    s.text(240, 327, "TCP 3000", "ts", "start")

    s.line([(120, 365), (120, 395), (830, 395)], "bad", arrow=False, dash=True)
    s.cross(850, 395)
    s.text(480, 391, "TCP 5432 desde tu PC / Internet: descartado", "tbad")

    s.rect(20, 410, 1020, 90, "box")
    s.text(36, 430, "REGLAS DE ENTRADA", "tz", "start")
    s.text(36, 450, "nextguard-sg  ←  TCP 8000  desde 0.0.0.0/0 (o solo la IP pública de tu WiFi, más estricto)  ·  TCP 3000  solo desde «Mi IP» (/32)", "t", "start")
    s.text(36, 468, "nextguard-sg  ←  TCP 22  solo desde «Mi IP» (/32); si tu IP pública cambia, actualiza las reglas 22 y 3000", "t", "start")
    s.text(36, 486, "TCP 5432  sin regla de entrada y sin puerto publicado en compose: solo existe dentro de la red docker", "t", "start")

    pagina("despliegue_aws.html", "Despliegue en AWS",
           "Recursos del Learner Lab y qué regla de red permite cada conexión.",
           s.render(),
           "Flechas verdes = conexiones permitidas. La línea roja discontinua es la que debe rechazarse: PostgreSQL no publica su puerto y el "
           "Security Group no tiene regla para 5432.",
           ["La sesión del laboratorio dura unas 4 h: al terminar, la EC2 se detiene. Sin Elastic IP, la IP pública cambia y hay que actualizar <code>API_HOST</code> en <code>config.h</code>. "
            "Los contenedores usan <code>restart: unless-stopped</code> y los datos viven en volúmenes nombrados, así que el stack vuelve solo al iniciar la EC2: el reinicio de la instancia ya se probó (IT-ENV-05, IT-ENV-08, IT-NFR-07).",
            "Detén la EC2 al cerrar cada sesión para no consumir presupuesto. Con el Elastic IP asociado, la IP de la API no cambia entre reinicios; los tipos de instancia disponibles pueden variar por laboratorio.",
            "Pasos de creación y comprobación en <code>docs/deploy_ec2.md</code> y <code>scripts/smoke_env.sh</code> (incluye <code>--externo</code> para el caso rojo)."])


# ---------------------------------------------------------------- 5. niveles
def niveles():
    cs = casos()
    por = {}
    for c in cs:
        por.setdefault(c["nivel"], []).append(c)
    W = 1060
    s = Svg(W, 470, "Qué componentes integra cada nivel de prueba, en orden de ejecución, con el número de casos por nivel")
    comp = [("Sensor DHT", "GPIO"), ("ESP32", "WiFi"), ("Red / Internet", "HTTP"), ("API · Docker", "SQL"), ("BD · PostgreSQL", None)]
    cx = [110, 280, 450, 620, 790]
    for (t, e), x in zip(comp, cx):
        s.box(x - 60, 20, 120, 46, t, [], "box acc")
        s.p.append(f'<line class="guide" x1="{x}" y1="66" x2="{x}" y2="420"/>')
    for i, ((t, e), x) in enumerate(zip(comp, cx)):
        if e:
            s.line([(x + 60, 43), (cx[i + 1] - 60, 43)])
            s.text(x + 85, 36, e, "ts")
    s.text(900, 40, "casos · A / S / M", "tz", "start")

    izq = lambda i: cx[i] - 60
    der = lambda i: cx[i] + 60
    filas = [  # (nivel, texto, desde, hasta, suave)
        ("N0", "Entorno AWS", 3, 4, False),
        ("N1", "Sensor ↔ ESP32", 0, 1, False),
        ("N2", "ESP32 ↔ red ↔ API", 1, 3, False),
        ("N3", "API ↔ BD", 3, 4, False),
        ("N4", "Extremo a extremo", 0, 4, False),
        ("N5", "No funcionales: latencia, carga, recuperación", 0, 4, True),
        ("N6", "Seguridad: entradas, claves, exposición", 2, 4, True),
    ]
    for i, (niv, txt, a, b, suave) in enumerate(filas):
        y = 90 + i * 48
        g = por[niv]
        cnt = Counter(c["tipo"] for c in g)
        s.badge(30, y + 17, str(i + 1), "acc")
        s.rect(izq(a), y, der(b) - izq(a), 34, "bar soft" if suave else "bar", 6)
        s.text(izq(a) + 12, y + 21, f"{niv} · {txt}", "tb", "start")
        s.text(900, y + 21, f"{len(g)}   ·   {cnt['A']} / {cnt['S']} / {cnt['M']}", "t", "start")
    total = Counter(c["tipo"] for c in cs)
    s.text(900, 90 + 7 * 48 + 8, f"Total {len(cs)}   ·   {total['A']} / {total['S']} / {total['M']}", "tb", "start")
    s.text(30, 452, "Orden de ejecución: 1 → 7.  A = automatizado (pytest) · S = semi-automático · M = manual", "ts", "start")

    pagina("estrategia_niveles.html", "Niveles de prueba",
           "Qué tramo del sistema toca cada nivel y en qué orden se ejecutan.",
           s.render(),
           "Cada barra cubre los componentes que ese nivel integra. Los niveles se ejecutan de arriba abajo: primero el entorno, "
           "luego cada unión por separado y solo después el camino completo. Las barras punteadas (N5, N6) no añaden una unión nueva: "
           "someten al conjunto a fallos, carga y ataques.",
           ["N2 y N3 concentran la mayor parte de los casos automatizados: con el simulador se prueban API y BD <strong>antes</strong> de depender del hardware.",
            "N4 y N5 son los que más necesitan el ESP32 real y sesiones de laboratorio largas (operación continua de 3 h).",
            "Los estados y resultados se registran en <code>casos_de_prueba.xlsx</code>; la hoja <em>Resumen</em> recalcula el avance por nivel."])


# ---------------------------------------------------------------- índice
def indice():
    tarjetas = [
        ("arquitectura.html", "Arquitectura bajo prueba", "Componentes, red y qué tramo cubre cada nivel."),
        ("flujo_datos.html", "Recorrido de una lectura", "Siete pasos y qué pasa cuando algo falla en cada uno."),
        ("secuencia_pruebas.html", "Secuencia de las pruebas", "Camino feliz, duplicado, 401, caída y verificación."),
        ("despliegue_aws.html", "Despliegue en AWS", "Una EC2 con tres contenedores, Security Group y reglas de entrada."),
        ("estrategia_niveles.html", "Niveles de prueba", "N0 a N6, componentes que integra cada uno y conteo de casos."),
    ]
    cards = "".join(f'<a class="card" href="{h}"><h2>{esc(t)}</h2><p>{esc(d)}</p></a>' for h, t, d in tarjetas)
    doc = f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light dark"><title>Diagramas del plan</title><style>{CSS}</style></head>
<body><main><nav><a href="index.html" aria-current="page">Índice</a></nav>
<h1>Diagramas del plan de integración</h1>
<p class="lead">ESP32 → API Python → PostgreSQL → Grafana, en contenedores Docker sobre una EC2 (AWS Learner Lab). Cada página contiene un diagrama y las notas para leerlo.</p>
<div class="cards">{cards}</div></main></body></html>
"""
    with open(os.path.join(SALIDA, "index.html"), "w", encoding="utf-8") as f:
        f.write(doc)


if __name__ == "__main__":
    os.makedirs(SALIDA, exist_ok=True)
    indice(); arquitectura(); flujo_datos(); secuencia(); despliegue(); niveles()
    print("Diagramas generados en", SALIDA)
