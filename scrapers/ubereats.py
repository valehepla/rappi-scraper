"""
Scraper para Uber Eats México (ubereats.com/mx).

Estrategia de scraping:
  1. Navegar a ubereats.com/mx
  2. Ingresar dirección de entrega mediante el selector de dirección
  3. Esperar a que cargue el listado de restaurantes
  4. Buscar McDonald's / OXXO según el producto objetivo
  5. Extraer: precio del producto, delivery fee, ETA, descuentos activos
  6. Tomar screenshot como evidencia

Limitaciones conocidas:
  - Requiere IP mexicana para ver disponibilidad real por zona
  - Los selectores CSS/XPath pueden cambiar sin previo aviso (SPA React)
  - Service fee solo visible en checkout (flujo incompleto sin compra)
  - Puede triggear CAPTCHA en runs repetitivos sin proxy
"""

import asyncio
import logging
import re
from typing import Dict, List, Optional

from .base import BaseScraper, ScrapingResult

logger = logging.getLogger(__name__)

# URL base de Uber Eats México
UBEREATS_BASE = "https://www.ubereats.com/mx"


class UberEatsScraper(BaseScraper):
    """Scraper para Uber Eats México con soporte para live y mock mode."""

    PLATFORM_NAME = "ubereats"
    BASE_DOMAIN = "ubereats.com"

    # Selectores (múltiples alternativas por si cambia el DOM)
    SEL_ADDRESS_INPUT = [
        '[data-testid="address-input"]',
        'input[placeholder*="dirección"]',
        'input[placeholder*="Ingresa"]',
        'input[aria-label*="dirección"]',
    ]
    SEL_ADDRESS_SUGGESTION = [
        '[data-testid="address-suggestion"]',
        'li[role="option"]',
        '[class*="AddressSuggestion"]',
    ]
    SEL_RESTAURANT_CARD = [
        '[data-testid="store-card"]',
        '[class*="StoreCard"]',
        'a[href*="/store/"]',
    ]
    SEL_DELIVERY_FEE = [
        '[data-testid="store-meta-delivery-fee"]',
        '[class*="DeliveryFee"]',
        'span[aria-label*="envío"]',
    ]
    SEL_ETA = [
        '[data-testid="store-meta-eta"]',
        '[class*="ETA"]',
        'span[aria-label*="minutos"]',
    ]
    SEL_MENU_ITEM = [
        '[data-testid="menu-item"]',
        '[class*="MenuItem"]',
        'div[role="button"][aria-label]',
    ]

    def __init__(self, headless: bool = True, proxy: Optional[str] = None):
        super().__init__(headless=headless, proxy=proxy)

    # ─── Helpers de UI ────────────────────────────────────────────────────────

    async def _try_selectors(self, selectors: List[str], timeout: int = 5_000) -> Optional[str]:
        """Intenta cada selector en orden y retorna el primero que existe."""
        for sel in selectors:
            try:
                await self.page.wait_for_selector(sel, timeout=timeout)
                return sel
            except Exception:
                continue
        return None

    async def _set_delivery_address(self, address: Dict) -> bool:
        """Ingresa la dirección de entrega en el UI de Uber Eats."""
        logger.info(f"[ubereats] Ingresando dirección: {address['full_address']}")
        try:
            # Buscar el input de dirección
            input_sel = await self._try_selectors(self.SEL_ADDRESS_INPUT, timeout=8_000)
            if not input_sel:
                logger.warning("[ubereats] No se encontró el input de dirección")
                return False

            await self._type_slowly(input_sel, address["full_address"])
            await asyncio.sleep(1.5)  # esperar autocomplete

            # Seleccionar la primera sugerencia
            suggestion_sel = await self._try_selectors(
                self.SEL_ADDRESS_SUGGESTION, timeout=5_000
            )
            if suggestion_sel:
                await self._wait_and_click(suggestion_sel)
                await asyncio.sleep(2.0)
                logger.info("[ubereats] Dirección seleccionada del autocomplete")
                return True
            else:
                await self.page.keyboard.press("Enter")
                await asyncio.sleep(2.0)
                return True

        except Exception as e:
            logger.warning(f"[ubereats] Error ingresando dirección: {e}")
            return False

    async def _navigate_to_restaurant(self, restaurant_name: str) -> bool:
        """Busca y navega al restaurante objetivo en el listado."""
        try:
            # Usar búsqueda si está disponible
            search_sel = await self._try_selectors(
                ['[data-testid="search-input"]', 'input[placeholder*="Buscar"]'],
                timeout=5_000,
            )
            if search_sel:
                await self._type_slowly(search_sel, restaurant_name)
                await asyncio.sleep(2.0)

            # Buscar la card del restaurante
            card_sel = await self._try_selectors(self.SEL_RESTAURANT_CARD, timeout=8_000)
            if not card_sel:
                logger.warning(f"[ubereats] No se encontró card para {restaurant_name}")
                return False

            # Hacer click en el primer resultado
            cards = await self.page.query_selector_all(card_sel)
            for card in cards:
                text = await card.text_content()
                if restaurant_name.lower() in (text or "").lower():
                    await card.click()
                    await asyncio.sleep(2.5)
                    return True

            # Si no encontramos match exacto, click en el primero
            if cards:
                await cards[0].click()
                await asyncio.sleep(2.5)
                return True

            return False
        except Exception as e:
            logger.warning(f"[ubereats] Error navegando a {restaurant_name}: {e}")
            return False

    async def _extract_restaurant_meta(self) -> Dict:
        """Extrae delivery fee y ETA del header del restaurante."""
        meta = {"delivery_fee": None, "eta_min": None, "eta_max": None}
        try:
            # Delivery fee
            fee_sel = await self._try_selectors(self.SEL_DELIVERY_FEE, timeout=5_000)
            if fee_sel:
                fee_text = await self.page.text_content(fee_sel)
                fee_match = re.search(r"\$?([\d,]+(?:\.\d+)?)", fee_text or "")
                if fee_match:
                    meta["delivery_fee"] = float(fee_match.group(1).replace(",", ""))
                elif "gratis" in (fee_text or "").lower() or "free" in (fee_text or "").lower():
                    meta["delivery_fee"] = 0.0

            # ETA
            eta_sel = await self._try_selectors(self.SEL_ETA, timeout=5_000)
            if eta_sel:
                eta_text = await self.page.text_content(eta_sel)
                # Formato: "20-30 min" o "25 min"
                range_match = re.search(r"(\d+)\s*[-–]\s*(\d+)", eta_text or "")
                single_match = re.search(r"(\d+)\s*min", eta_text or "")
                if range_match:
                    meta["eta_min"] = int(range_match.group(1))
                    meta["eta_max"] = int(range_match.group(2))
                elif single_match:
                    base = int(single_match.group(1))
                    meta["eta_min"] = base
                    meta["eta_max"] = base + 10

        except Exception as e:
            logger.warning(f"[ubereats] Error extrayendo meta del restaurante: {e}")

        return meta

    async def _extract_product_price(self, product: Dict) -> Optional[float]:
        """Busca un producto en el menú y extrae su precio."""
        try:
            menu_sel = await self._try_selectors(self.SEL_MENU_ITEM, timeout=8_000)
            if not menu_sel:
                return None

            items = await self.page.query_selector_all(menu_sel)
            for item in items:
                text = await item.text_content()
                text_lower = (text or "").lower()
                # Buscar coincidencia con alguno de los search_terms
                for term in product.get("search_terms", [product["name"]]):
                    if term.lower() in text_lower:
                        # Extraer precio del mismo elemento
                        price_match = re.search(r"\$\s*([\d,]+(?:\.\d+)?)", text or "")
                        if price_match:
                            return float(price_match.group(1).replace(",", ""))

            return None
        except Exception as e:
            logger.warning(f"[ubereats] Error extrayendo precio de {product['name']}: {e}")
            return None

    async def _extract_discounts(self) -> List[str]:
        """Extrae promociones y descuentos visibles en la página."""
        discounts = []
        try:
            promo_selectors = [
                '[data-testid="promotion-tag"]',
                '[class*="PromotionTag"]',
                '[class*="discount"]',
                'span[class*="offer"]',
            ]
            for sel in promo_selectors:
                elements = await self.page.query_selector_all(sel)
                for el in elements:
                    text = await el.text_content()
                    if text and len(text.strip()) > 2:
                        discounts.append(text.strip())
        except Exception as e:
            logger.warning(f"[ubereats] Error extrayendo descuentos: {e}")
        return list(set(discounts))[:5]  # máx 5, sin duplicados

    # ─── Scraping principal ───────────────────────────────────────────────────

    async def scrape_address(
        self, address: Dict, products: List[Dict]
    ) -> List[ScrapingResult]:
        """
        Scrapea todos los productos para una dirección en Uber Eats.
        Flujo: homepage → set address → restaurant → extract data
        """
        results = []

        # Navegar a Uber Eats México
        success = await self._navigate(UBEREATS_BASE)
        if not success:
            for product in products:
                r = ScrapingResult(
                    self.PLATFORM_NAME, address, product,
                    status="error", error="No se pudo cargar ubereats.com/mx"
                )
                results.append(r)
            return results

        await self._screenshot(f"{address['id']}_homepage")

        # Ingresar dirección
        addr_ok = await self._set_delivery_address(address)
        if not addr_ok:
            logger.warning(f"[ubereats] No se pudo ingresar dirección para {address['id']}")

        await self._screenshot(f"{address['id']}_after_address")

        # Agrupar productos por restaurante para una sola navegación
        restaurants: Dict[str, List[Dict]] = {}
        for product in products:
            restaurants.setdefault(product["restaurant"], []).append(product)

        for restaurant_name, rest_products in restaurants.items():
            logger.info(f"[ubereats] Navegando a {restaurant_name} en {address['id']}")

            rest_ok = await self._navigate_to_restaurant(restaurant_name)
            if not rest_ok:
                for product in rest_products:
                    r = ScrapingResult(
                        self.PLATFORM_NAME, address, product,
                        status="error",
                        error=f"Restaurante {restaurant_name} no encontrado"
                    )
                    results.append(r)
                continue

            await self._screenshot(f"{address['id']}_{restaurant_name.replace(' ', '_')}")

            # Extraer metadata del restaurante (fees, ETA) — una sola vez por restaurante
            meta = await self._extract_restaurant_meta()
            discounts = await self._extract_discounts()

            # Extraer precio de cada producto
            for product in rest_products:
                r = ScrapingResult(self.PLATFORM_NAME, address, product)
                r.delivery_fee = meta.get("delivery_fee")
                r.estimated_delivery_min = meta.get("eta_min")
                r.estimated_delivery_max = meta.get("eta_max")
                r.discounts_active = discounts

                price = await self._extract_product_price(product)
                r.price_product = price

                if price and r.delivery_fee is not None:
                    # Service fee estimado (no visible sin checkout)
                    r.service_fee = round(price * 0.06, 2)
                    r.final_price_total = round(
                        price + r.delivery_fee + r.service_fee, 2
                    )

                r.screenshot_path = await self._screenshot(
                    f"{address['id']}_{product['id']}"
                )
                results.append(r)

            # Volver al listado para el siguiente restaurante
            await self.page.go_back()
            await asyncio.sleep(1.5)

        return results
