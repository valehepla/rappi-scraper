"""
Scraper para DiDi Food México (food.didiglobal.com).

Estrategia de scraping:
  1. Navegar a food.didiglobal.com
  2. Seleccionar México como región
  3. Ingresar dirección de entrega
  4. Buscar y navegar a McDonald's / OXXO
  5. Extraer: precio del producto, delivery fee, ETA, descuentos
  6. Tomar screenshot como evidencia

Limitaciones conocidas:
  - DiDi Food tiene menor cobertura que Rappi/Uber Eats en zonas periféricas
  - El sitio puede redirigir según geolocalización del IP
  - Los selectores CSS son menos estables que los de Uber Eats/Rappi
  - En Guadalajara la disponibilidad y precios difieren notablemente del resto
"""

import asyncio
import logging
import re
from typing import Dict, List, Optional

from .base import BaseScraper, ScrapingResult

logger = logging.getLogger(__name__)

DIDIFOOD_BASE = "https://food.didiglobal.com"
DIDIFOOD_MX = "https://food.didiglobal.com/mx"


class DiFoodScraper(BaseScraper):
    """Scraper para DiDi Food México."""

    PLATFORM_NAME = "didifood"
    BASE_DOMAIN = "didiglobal.com"

    SEL_LOCATION_INPUT = [
        'input[placeholder*="dirección"]',
        'input[placeholder*="Ingresa"]',
        'input[class*="location"]',
        'input[data-testid*="location"]',
    ]
    SEL_RESTAURANT_CARD = [
        '[class*="restaurant-card"]',
        '[class*="StoreCard"]',
        'a[href*="/restaurant/"]',
        'div[data-testid*="store"]',
    ]
    SEL_DELIVERY_INFO = [
        '[class*="delivery-info"]',
        '[class*="delivery-fee"]',
        'span[class*="fee"]',
    ]
    SEL_ETA = [
        '[class*="delivery-time"]',
        '[class*="eta"]',
        'span[class*="time"]',
    ]

    async def _try_selectors(self, selectors: List[str], timeout: int = 5_000) -> Optional[str]:
        for sel in selectors:
            try:
                await self.page.wait_for_selector(sel, timeout=timeout)
                return sel
            except Exception:
                continue
        return None

    async def _handle_region_selector(self):
        """Maneja el selector de región si DiDi lo muestra al entrar."""
        try:
            region_sels = [
                'button[aria-label*="México"]',
                'a[href*="/mx"]',
                'div[class*="country"][data-value*="mx"]',
            ]
            for sel in region_sels:
                try:
                    el = await self.page.wait_for_selector(sel, timeout=3_000)
                    if el:
                        await el.click()
                        await asyncio.sleep(1.5)
                        return
                except Exception:
                    continue
        except Exception:
            pass

    async def _set_delivery_address(self, address: Dict) -> bool:
        """Ingresa la dirección de entrega en DiDi Food."""
        logger.info(f"[didifood] Ingresando dirección: {address['full_address']}")
        try:
            await self._handle_region_selector()

            input_sel = await self._try_selectors(self.SEL_LOCATION_INPUT, timeout=7_000)
            if not input_sel:
                logger.warning("[didifood] No se encontró input de dirección")
                return False

            await self._type_slowly(input_sel, address["full_address"])
            await asyncio.sleep(1.5)

            suggestion_sel = await self._try_selectors(
                ['li[role="option"]', '[class*="suggestion"]', '[class*="autocomplete-item"]'],
                timeout=4_000,
            )
            if suggestion_sel:
                await self._wait_and_click(suggestion_sel)
            else:
                await self.page.keyboard.press("Enter")

            await asyncio.sleep(2.5)
            return True

        except Exception as e:
            logger.warning(f"[didifood] Error configurando dirección: {e}")
            return False

    async def _navigate_to_restaurant(self, restaurant_name: str) -> bool:
        """Busca y navega al restaurante en DiDi Food."""
        try:
            search_sels = [
                'input[placeholder*="Buscar"]',
                'input[type="search"]',
                '[data-testid="search"]',
            ]
            search_sel = await self._try_selectors(search_sels, timeout=5_000)
            if search_sel:
                await self._type_slowly(search_sel, restaurant_name)
                await asyncio.sleep(2.0)

            card_sel = await self._try_selectors(self.SEL_RESTAURANT_CARD, timeout=8_000)
            if not card_sel:
                return False

            cards = await self.page.query_selector_all(card_sel)
            for card in cards:
                text = await card.text_content()
                if restaurant_name.lower() in (text or "").lower():
                    await card.click()
                    await asyncio.sleep(2.5)
                    return True

            if cards:
                await cards[0].click()
                await asyncio.sleep(2.5)
                return True

            return False
        except Exception as e:
            logger.warning(f"[didifood] Error navegando a {restaurant_name}: {e}")
            return False

    async def _extract_restaurant_meta(self) -> Dict:
        """Extrae delivery fee y ETA de la página de restaurante en DiDi Food."""
        meta = {"delivery_fee": None, "eta_min": None, "eta_max": None}
        try:
            delivery_sel = await self._try_selectors(self.SEL_DELIVERY_INFO, timeout=5_000)
            if delivery_sel:
                text = await self.page.text_content(delivery_sel)
                if "gratis" in (text or "").lower() or "$0" in (text or ""):
                    meta["delivery_fee"] = 0.0
                else:
                    m = re.search(r"\$?\s*([\d,]+(?:\.\d+)?)", text or "")
                    if m:
                        meta["delivery_fee"] = float(m.group(1).replace(",", ""))

            eta_sel = await self._try_selectors(self.SEL_ETA, timeout=5_000)
            if eta_sel:
                eta_text = await self.page.text_content(eta_sel)
                range_m = re.search(r"(\d+)\s*[-–]\s*(\d+)", eta_text or "")
                single_m = re.search(r"(\d+)\s*min", eta_text or "")
                if range_m:
                    meta["eta_min"] = int(range_m.group(1))
                    meta["eta_max"] = int(range_m.group(2))
                elif single_m:
                    v = int(single_m.group(1))
                    meta["eta_min"] = v
                    meta["eta_max"] = v + 10
        except Exception as e:
            logger.warning(f"[didifood] Error extrayendo meta: {e}")
        return meta

    async def _extract_product_price(self, product: Dict) -> Optional[float]:
        """Extrae precio del producto en el menú de DiDi Food."""
        try:
            item_sel = await self._try_selectors(
                [
                    '[class*="food-item"]',
                    '[class*="product-item"]',
                    '[class*="menu-item"]',
                    'div[class*="dish"]',
                ],
                timeout=8_000,
            )
            if not item_sel:
                return None

            items = await self.page.query_selector_all(item_sel)
            for item in items:
                text = await item.text_content()
                for term in product.get("search_terms", [product["name"]]):
                    if term.lower() in (text or "").lower():
                        m = re.search(r"\$\s*([\d,]+(?:\.\d+)?)", text or "")
                        if m:
                            return float(m.group(1).replace(",", ""))
            return None
        except Exception as e:
            logger.warning(f"[didifood] Error extrayendo precio de {product['name']}: {e}")
            return None

    async def _extract_discounts(self) -> List[str]:
        """Extrae descuentos visibles en DiDi Food."""
        discounts = []
        try:
            promo_sels = [
                '[class*="promo-tag"]',
                '[class*="discount"]',
                '[class*="offer"]',
                'span[class*="badge"]',
            ]
            for sel in promo_sels:
                els = await self.page.query_selector_all(sel)
                for el in els:
                    text = await el.text_content()
                    if text and len(text.strip()) > 2:
                        discounts.append(text.strip())
        except Exception as e:
            logger.warning(f"[didifood] Error extrayendo descuentos: {e}")
        return list(set(discounts))[:5]

    async def scrape_address(
        self, address: Dict, products: List[Dict]
    ) -> List[ScrapingResult]:
        """Scrapea todos los productos para una dirección en DiDi Food."""
        results = []

        # Intentar URL México directa, luego base
        success = await self._navigate(DIDIFOOD_MX)
        if not success:
            success = await self._navigate(DIDIFOOD_BASE)
        if not success:
            for product in products:
                r = ScrapingResult(
                    self.PLATFORM_NAME, address, product,
                    status="error", error="No se pudo cargar DiDi Food"
                )
                results.append(r)
            return results

        await self._screenshot(f"{address['id']}_homepage")
        await self._set_delivery_address(address)
        await self._screenshot(f"{address['id']}_after_address")

        restaurants: Dict[str, List[Dict]] = {}
        for product in products:
            restaurants.setdefault(product["restaurant"], []).append(product)

        for restaurant_name, rest_products in restaurants.items():
            logger.info(f"[didifood] Navegando a {restaurant_name} en {address['id']}")

            rest_ok = await self._navigate_to_restaurant(restaurant_name)
            if not rest_ok:
                for product in rest_products:
                    r = ScrapingResult(
                        self.PLATFORM_NAME, address, product,
                        status="error",
                        error=f"Restaurante {restaurant_name} no encontrado en DiDi Food"
                    )
                    results.append(r)
                continue

            await self._screenshot(f"{address['id']}_{restaurant_name.replace(' ', '_')}")

            meta = await self._extract_restaurant_meta()
            discounts = await self._extract_discounts()

            for product in rest_products:
                r = ScrapingResult(self.PLATFORM_NAME, address, product)
                r.delivery_fee = meta.get("delivery_fee")
                r.estimated_delivery_min = meta.get("eta_min")
                r.estimated_delivery_max = meta.get("eta_max")
                r.discounts_active = discounts

                price = await self._extract_product_price(product)
                r.price_product = price

                if price and r.delivery_fee is not None:
                    r.service_fee = round(price * 0.04, 2)
                    r.final_price_total = round(
                        price + r.delivery_fee + r.service_fee, 2
                    )

                r.screenshot_path = await self._screenshot(
                    f"{address['id']}_{product['id']}"
                )
                results.append(r)

            await self.page.go_back()
            await asyncio.sleep(1.5)

        return results
