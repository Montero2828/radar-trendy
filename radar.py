#!/usr/bin/env python3
"""Radar Trendy: avisa por ntfy cuando aparece o queda disponible el calendario.

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
import urllib.parse
import urllib.request

BASE = "https://www.maquillajetrendyshop.com"
KEYWORDS = ["calendario", "adviento"]  # palabras que debe tener el nombre
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


def fetch(keyword):
    """Busca en el catálogo público de VTEX (la plataforma de la tienda)."""
    url = (f"{BASE}/api/catalog_system/pub/products/search"
           f"?ft={urllib.parse.quote(keyword)}&_from=0&_to=49")
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.load(resp)


def offer(product):
    """Primera oferta del producto, o {} si no hay."""
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


def notify(title, message, click=BASE, priority="urgent", tags="rotating_light"):
    # Los encabezados HTTP deben ser ASCII/latin-1: el título va sin emojis.
    req = urllib.request.Request(
        f"https://ntfy.sh/{TOPIC}",
        data=message.encode("utf-8"),
        method="POST",
        headers={"Title": title, "Priority": priority, "Tags": tags, "Click": click},
    )
    urllib.request.urlopen(req, timeout=20).read()


def check():
    seen = {}
    if os.path.exists(STATE):
        with open(STATE, encoding="utf-8") as f:
            seen = json.load(f)

    found = {}
    for kw in KEYWORDS:
        for product in fetch(kw):
            name = norm(product.get("productName", ""))
            if any(k in name for k in KEYWORDS):
                found[str(product["productId"])] = product

    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} - coincidencias: {len(found)}")
    for pid, product in found.items():
        state = "disponible" if is_available(product) else "agotado"
        last = seen.get(pid)
        if state != last and (state == "disponible" or last is None):
            price = offer(product).get("Price")
            price_txt = f"\nPrecio: ${price:,.0f}".replace(",", ".") if price else ""
            if state == "disponible":
                title = "Trendy: YA HAY CALENDARIO"
                body = f"{product['productName']} esta disponible para comprar.{price_txt}"
            else:
                title = "Trendy: aparecio en el catalogo"
                body = f"{product['productName']} ya aparece, pero aun sin stock.{price_txt}"
            notify(title, body, click=product.get("link", BASE))
            print("  notificado:", product["productName"], state)
        seen[pid] = state

    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(seen, f, ensure_ascii=False, indent=2)


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
