#!/usr/bin/env python3
"""Radar Trendy: avisa por ntfy de productos nuevos y de productos que vuelven a tener stock.

Uso:
  NTFY_TOPIC=tu-tema python radar.py           # una revisión
  NTFY_TOPIC=tu-tema python radar.py --loop    # revisa cada 60 s (para tu PC)
  NTFY_TOPIC=tu-tema python radar.py --test    # manda una notificación de prueba
"""
import json
import os
import sys
import time
import unicodedata
import urllib.error
import urllib.request

BASE = "https://www.maquillajetrendyshop.com"
KEYWORDS = ["calendario", "adviento"]  # estos se avisan como urgentes
MAX_SUELTOS = 8  # máximo de avisos sueltos por revisión; el resto va en un resumen
STATE = "seen.json"
TOPIC = os.environ.get("NTFY_TOPIC", "").strip()
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "application/json",
}


def norm(text):
    """Minúsculas y sin tildes, para comparar nombres."""
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()


def get_json(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def fetch_all():
    """Trae todo el catálogo público de VTEX (50 por página), lo más nuevo primero."""
    products = {}
    start = 0
    while start < 2500:  # tope de la API de VTEX
        url = (f"{BASE}/api/catalog_system/pub/products/search"
               f"?O=OrderByReleaseDateDESC&_from={start}&_to={start + 49}")
        try:
            page = get_json(url)
        except urllib.error.HTTPError as exc:
            if start > 0 and exc.code == 400:  # nos pasamos del final del catálogo
                break
            raise
        for p in page:
            products[str(p["productId"])] = p
        if len(page) < 50:
            break
        start += 50
        time.sleep(0.3)
    return products


def offer(product):
    for item in product.get("items", []):
        for seller in item.get("sellers", []):
            return seller.get("commertialOffer", {})
    return {}


def is_available(product):
    for item in product.get("items", []):
        for seller in item.get("sellers", []):
            if seller.get("commertialOffer", {}).get("AvailableQuantity", 0) > 0:
                return True
    return False


def is_calendar(product):
    name = norm(product.get("productName", ""))
    return any(k in name for k in KEYWORDS)


def url_of(product):
    if product.get("link"):
        return product["link"]
    if product.get("linkText"):
        return f"{BASE}/{product['linkText']}/p"
    return BASE


def notify(title, message, click=BASE, priority="default", tags="bell"):
    # Los encabezados HTTP deben ser ASCII/latin-1: el título va sin emojis.
    req = urllib.request.Request(
        f"https://ntfy.sh/{TOPIC}",
        data=message.encode("utf-8"),
        method="POST",
        headers={"Title": title, "Priority": priority, "Tags": tags, "Click": click},
    )
    urllib.request.urlopen(req, timeout=20).read()


def send_event(product, kind, state):
    name = product.get("productName", "Producto")
    price = offer(product).get("Price")
    price_txt = f"\nPrecio: ${price:,.0f}".replace(",", ".") if price else ""
    stock_txt = "\n(sin stock por ahora)" if state == "agotado" else ""
    cal = is_calendar(product)
    if cal and state == "disponible":
        title, prio, tags = "Trendy: YA HAY CALENDARIO", "urgent", "rotating_light"
    elif cal:
        title, prio, tags = "Trendy: calendario aparecio (sin stock)", "high", "eyes"
    elif kind == "nuevo":
        title, prio, tags = "Trendy: producto nuevo", "default", "new"
    else:
        title, prio, tags = "Trendy: de vuelta en stock", "default", "package"
    notify(title, f"{name}{price_txt}{stock_txt}", click=url_of(product),
           priority=prio, tags=tags)


def check():
    seen = {}
    if os.path.exists(STATE):
        with open(STATE, encoding="utf-8") as f:
            seen = json.load(f)
    baseline = "_init" not in seen  # primera vez: registrar todo en silencio

    found = fetch_all()
    if not found:
        raise RuntimeError("La tienda devolvio 0 productos; no se actualiza nada")

    events = []
    for pid, product in found.items():
        state = "disponible" if is_available(product) else "agotado"
        last = seen.get(pid)
        if last is None:
            kind = "nuevo"
        elif last == "agotado" and state == "disponible":
            kind = "stock"
        else:
            kind = None
        # En la primera vez solo se avisa de calendarios; el resto se registra callado.
        if kind and not (baseline and not is_calendar(product)):
            events.append((product, kind, state))
        seen[pid] = state
    seen["_init"] = True

    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} - productos: {len(found)}, "
          f"avisos: {len(events)}, primera vez: {baseline}")

    events.sort(key=lambda e: not is_calendar(e[0]))  # calendarios primero
    sueltos = resto = 0
    for product, kind, state in events:
        if not is_calendar(product):
            if sueltos >= MAX_SUELTOS:
                resto += 1
                continue
            sueltos += 1
        send_event(product, kind, state)
        print("  notificado:", kind, product.get("productName"), state)
    if resto:
        notify("Trendy: mas movimiento en la tienda",
               f"Y {resto} productos mas entre nuevos y de vuelta en stock.",
               click=f"{BASE}/nueva-coleccion", tags="new")
    if baseline:
        notify("Radar Trendy: listo",
               f"Registre {len(found)} productos. Desde ahora te aviso de cada producto "
               "nuevo y de los que vuelvan a tener stock.",
               priority="low", tags="white_check_mark")

    # El estado se guarda al final: si algo falla antes, se reintenta en la próxima.
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(seen, f, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


if __name__ == "__main__":
    if not TOPIC:
        sys.exit("Falta la variable de entorno NTFY_TOPIC")
    if "--test" in sys.argv:
        notify("Radar Trendy: prueba", "Si ves esto, las notificaciones funcionan.",
               priority="default", tags="white_check_mark")
    elif "--loop" in sys.argv:
        while True:
            try:
                check()
            except Exception as exc:  # no se cae por un error de red puntual
                print("error:", exc)
            time.sleep(60)
    else:
        check()
