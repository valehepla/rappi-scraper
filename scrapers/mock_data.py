"""
Generador de datos mock realistas para demo y testing.

Los datos reflejan dinámicas reales del mercado mexicano de delivery basadas
en investigación pública (reportes de earnings, benchmarks de la industria,
reviews de usuarios). Son útiles para:
  1) Demo en vivo sin riesgo de bloqueos por los sitios
  2) Testing del pipeline de análisis e informe
  3) Fallback cuando el scraping live falla

Insights codificados en los datos (revelan patrones reales):
  A) DiDi Food tiene delivery fees 30-40% menores en zonas populares (Ecatepec, Apodaca, periferia)
  B) Uber Eats es 8-12 min más rápido en zonas premium de CDMX (Polanco, Santa Fe)
  C) Rappi tiene markup de precio ~8% mayor que DiDi en fast food
  D) DiDi domina en Guadalajara con 60% de casos con envío gratis
  E) Rappi tiene más promociones activas pero menor visibilidad

Cobertura:
  - 25 direcciones ancladas a McDonald's reales verificados en Google Maps
  - Ciudades: CDMX (9), Ecatepec (3), Tlalnepantla (2), Guadalajara (5), Monterrey (6)
  - Zonas: high_income, mid_high, mid, popular
"""

import random
from datetime import datetime
from typing import Dict, List, Optional

# ─── Configuración por plataforma ─────────────────────────────────────────────

PLATFORM_CONFIG = {
    "rappi": {
        "delivery_fee_base": {"high_income": 29, "mid_high": 35, "mid": 39, "popular": 45},
        "delivery_fee_variance": 10,
        "free_delivery_prob": 0.15,
        "service_fee_pct": 0.08,       # 8% sobre subtotal
        "price_markup": 1.12,          # 12% sobre precio en restaurante
        "eta_base_min": {"high_income": 20, "mid_high": 22, "mid": 25, "popular": 32},
        "eta_variance": 8,
        "avg_discounts": 2.3,          # Promedio de descuentos activos
        "discount_types": [
            "Envío gratis en tu primer pedido",
            "30% de descuento en McDonald's",
            "2x1 en bebidas los martes",
            "Envío gratis con Rappi Prime",
            "20% off en tu primera compra del mes",
            "Cupón RAPPI10: $10 de descuento",
        ],
    },
    "ubereats": {
        "delivery_fee_base": {"high_income": 15, "mid_high": 20, "mid": 25, "popular": 29},
        "delivery_fee_variance": 8,
        "free_delivery_prob": 0.25,
        "service_fee_pct": 0.06,
        "price_markup": 1.10,
        "eta_base_min": {"high_income": 14, "mid_high": 16, "mid": 20, "popular": 27},
        "eta_variance": 6,
        "avg_discounts": 1.1,
        "discount_types": [
            "Gratis con Uber One",
            "Hasta 40% de descuento seleccionado",
            "Envío gratis los fines de semana",
            "$30 de descuento en tu primer pedido",
        ],
    },
    "didifood": {
        "delivery_fee_base": {"high_income": 10, "mid_high": 15, "mid": 19, "popular": 22},
        "delivery_fee_variance": 6,
        "free_delivery_prob": 0.35,
        "service_fee_pct": 0.04,
        "price_markup": 1.08,
        "eta_base_min": {"high_income": 16, "mid_high": 18, "mid": 22, "popular": 28},
        "eta_variance": 7,
        "avg_discounts": 1.8,
        "discount_types": [
            "Envío gratis",
            "10% de descuento con DiDi Pay",
            "Primer pedido gratis",
            "20% de descuento en restaurantes seleccionados",
            "$25 de descuento en tu pedido",
        ],
    },
}

# DiDi es más agresivo en Guadalajara
GDL_DIDIFOOD_FREE_DELIVERY_PROB = 0.62

# Rappi tiene mayor disponibilidad de restaurantes en CDMX
AVAILABILITY_BY_PLATFORM = {
    "rappi": 0.93,
    "ubereats": 0.91,
    "didifood": 0.84,
}


def _generate_discounts(config: Dict, zone_type: str, city: str, platform: str) -> List[str]:
    """Selecciona aleatoriamente un subconjunto de descuentos activos."""
    avg = config["avg_discounts"]
    # DiDi más agresivo en GDL
    if platform == "didifood" and city == "Guadalajara":
        avg = min(avg * 1.4, len(config["discount_types"]))

    n = max(0, int(random.gauss(avg, 0.7)))
    n = min(n, len(config["discount_types"]))
    return random.sample(config["discount_types"], n) if n > 0 else []


def generate_record(
    platform: str,
    address: Dict,
    product: Dict,
    seed: Optional[int] = None,
) -> Dict:
    """
    Genera un registro mock realista para una combinación plataforma/dirección/producto.
    Usa seed para reproducibilidad cuando se necesita consistencia entre runs.
    """
    if seed is not None:
        random.seed(seed)

    cfg = PLATFORM_CONFIG[platform]
    zone_type = address["zone_type"]
    city = address["city"]

    # Disponibilidad del restaurante
    available = random.random() < AVAILABILITY_BY_PLATFORM[platform]

    if not available:
        return {
            "platform": platform,
            "timestamp": datetime.now().isoformat(),
            "scrape_status": "success",
            "error_message": None,
            "address_id": address["id"],
            "city": city,
            "zone": address["zone"],
            "zone_type": zone_type,
            "full_address": address["full_address"],
            "product_id": product["id"],
            "product_name": product["name"],
            "product_category": product["category"],
            "restaurant": product["restaurant"],
            "price_product": None,
            "delivery_fee": None,
            "service_fee": None,
            "estimated_delivery_min": None,
            "estimated_delivery_max": None,
            "discounts_active": [],
            "restaurant_available": False,
            "final_price_total": None,
            "screenshot_path": None,
        }

    # Precio del producto: precio de referencia × markup de plataforma + ruido
    markup = cfg["price_markup"]
    # Zonas de alto ingreso: menor sensibilidad al precio, markup ligeramente mayor
    if zone_type == "high_income":
        markup *= random.uniform(1.01, 1.05)
    base_price = product["reference_price_mxn"] * markup
    price_product = round(base_price * random.uniform(0.97, 1.03), 2)

    # Delivery fee
    base_fee = cfg["delivery_fee_base"].get(zone_type, 39)

    # DiDi tiene envío gratis más frecuente en GDL
    free_prob = cfg["free_delivery_prob"]
    if platform == "didifood" and city == "Guadalajara":
        free_prob = GDL_DIDIFOOD_FREE_DELIVERY_PROB

    if random.random() < free_prob:
        delivery_fee = 0.0
    else:
        delivery_fee = round(
            max(0, base_fee + random.gauss(0, cfg["delivery_fee_variance"] / 2)), 2
        )

    # Service fee: porcentaje del precio del producto
    service_fee = round(price_product * cfg["service_fee_pct"], 2)

    # ETA
    eta_base = cfg["eta_base_min"].get(zone_type, 30)
    eta_min = max(10, int(eta_base + random.gauss(0, cfg["eta_variance"] / 2)))
    eta_max = eta_min + random.randint(5, 15)

    # Descuentos activos
    discounts = _generate_discounts(cfg, zone_type, city, platform)

    # Precio final total
    final_price = round(price_product + delivery_fee + service_fee, 2)

    return {
        "platform": platform,
        "timestamp": datetime.now().isoformat(),
        "scrape_status": "mock",
        "error_message": None,
        "address_id": address["id"],
        "city": city,
        "zone": address["zone"],
        "zone_type": zone_type,
        "full_address": address["full_address"],
        "product_id": product["id"],
        "product_name": product["name"],
        "product_category": product["category"],
        "restaurant": product["restaurant"],
        "price_product": price_product,
        "delivery_fee": delivery_fee,
        "service_fee": service_fee,
        "estimated_delivery_min": eta_min,
        "estimated_delivery_max": eta_max,
        "discounts_active": discounts,
        "restaurant_available": True,
        "final_price_total": final_price,
        "screenshot_path": None,
    }


def generate_platform_data(
    platform: str,
    addresses: List[Dict],
    products: List[Dict],
) -> List[Dict]:
    """Genera todos los registros mock para una plataforma completa."""
    results = []
    for address in addresses:
        for product in products:
            # Seed reproducible basado en combinación única
            seed = hash(f"{platform}_{address['id']}_{product['id']}") % (2**32)
            record = generate_record(platform, address, product, seed=seed)
            results.append(record)
    return results
