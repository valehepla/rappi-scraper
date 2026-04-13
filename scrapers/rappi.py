"""
Scraper para Rappi México (rappi.com.mx).

Estrategia de scraping:
  1. Navegar a rappi.com.mx
  2. Ingresar dirección de entrega
  3. Buscar y navegar a McDonald's / OXXO
  4. Extraer: precio del producto, delivery fee, ETA, descuentos
  5. Tomar screenshot como evidencia

Limitaciones conocidas:
  - Requiere IP mexicana para cobertura real por zona
  - Rappi usa Cloudflare — pueden surgir desafíos 403/captcha
  - El service fee es visible en la página de checkout (no extraído aquí)
  - La app móvil tiene más datos que la web; la web es más scrapeable
"""

import asyncio
import logging
import re
from typing import Dict, List, Optional

from .base import BaseScraper, ScrapingResult

logger = logging.getLogger(__name__)

RAPPI_BASE = "https://www.rappi.com.mx"


class RappiScraper(BaseScraper):
    """Scraper para Rappi México."""

    PLATFORM_NAME = "rappi"
    BASE_DOMAIN = "rappi.com.mx"

    SEL_ADDRESS_BTN = [
        'button[data-testid*="address"]',
        'button[aria-label*="dirección"]',
        '[class*="AddressButton"]',
        'span[class*="address"]',
    ]
    SEL_ADDRESS_INPUT = [
        'input[placeholder*="dirección"]',
        'input[placeholder*="Busca tu"]',
        'input[data-testid="address-input"]',
        'input[type="text"][name*="address"]',
    ]
    SEL_RESTAURANT_ITEM = [
        '[data-testid="store-item"]',
        'a[href*="/restaurantes/"]',
        '[class*="StoreCard"]',
        'div[class*="restaurant-card"]',
    ]
    SEL_DELIVERY_FEE = [
        '[data-testid="delivery-fee"]',
        '[class*="delivery-fee"]',
        'span[class*="DeliveryFee"]',
        'p[class*="cost"]',
    ]
    SEL_ETA = [
        '[data-testid="delivery-eta"]',
        '[class*="delivery-time"]',
        'span[class*="eta"]',
        'p[class*="time"]',
    ]

    async def _try_selectors(self, selectors: List[str], timeout: int = 5_000) -> Optional[str]:
        for sel in selectors:
            try:
                await self.page.wait_for_selector(sel, timeout=timeout)
                return sel
            except Exception:
                continue
        return None

    async def _set_delivery_address(self, address: Dict) -> bool:
        """Ingresa la dirección de entrega en Rappi."""
        logger.info(f"[rappi] Ingresando dirección: {address['full_address']}")
        try:
            # Click en el botón de dirección actual si existe
            btn_sel = await self._try_selectors(self.SEL_ADDRESS_BTN, timeout=6_000)
            if btn_sel:
                await self._wait_and_click(btn_sel)
                await asyncio.sleep(1.0)

            # Buscar el input y escribir la dirección
            input_sel = await self._try_selectors(self.SEL_ADDRESS_INPUT, timeout=5_000)
            if not input_sel:
                logger.warning("[rappi] No se encontró input de dirección")
                return False

            # Limpiar y escribir
            await self.page.click(input_sel, click_count=3)
            await self.page.keyboard.press("Control+a")
            await self._type_slowly(input_sel, address["full_address"])
            await asyncio.sleep(1.5)

            # Seleccionar primera sugerencia
            suggestion_sel = await self._try_selectors(
                ['li[role="option"]', '[class*="suggestion"]', '[class*="Suggestion"]'],
                timeout=4_000,
            )
            if suggestion_sel:
                await self._wait_and_click(suggestion_sel)
            else:
                await self.page.keyboard.press("Enter")

            await asyncio.sleep(2.5)
            logger.info("[rappi] Dirección configurada")
            return True

        except Exception as e:
            logger.warning(f"[rappi] Error configurando dirección: {e}")
            return False

    async def _search_restaurant(self, restaurant_name: str) -> bool:
        """Busca el restaurante usando la barra de búsqueda de Rappi."""
        try:
            # Intentar usar la búsqueda global
            search_sel = await self._try_selectors(
                [
                    'input[placeholder*="Buscar"]',
                    'input[placeholder*="buscar"]',
                    '[data-testid="search-input"]',
                    'input[type="search"]',
                ],
                timeout=6_000,
            )
            if search_sel:
                await self._type_slowly(search_sel, restaurant_name)
                await asyncio.sleep(2.0)

            # Click en el resultado del restaurante
            card_sel = await self._try_selectors(self.SEL_RESTAURANT_ITEM, timeout=8_000)
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
            logger.warning(f"[rappi] Error buscando {restaurant_name}: {e}")
            return False

    async def _extract_restaurant_meta(self) -> Dict:
        """Extrae delivery fee y ETA de la página del restaurante en Rappi."""
        meta = {"delivery_fee": None, "eta_min": None, "eta_max": None}
        try:
            fee_sel = await self._try_selectors(self.SEL_DELIVERY_FEE, timeout=5_000)
            if fee_sel:
                fee_text = await self.page.text_content(fee_sel)
                if "gratis" in (fee_text or "").lower():
                    meta["delivery_fee"] = 0.0
                else:
                    m = re.search(r"\$?\s*([\d,]+(?:\.\d+)?)", fee_text or "")
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
            logger.warning(f"[rappi] Error extrayendo meta: {e}")
        return meta

    async def _extract_product_price(self, product: Dict) -> Optional[float]:
        """Extrae el precio del producto en el menú de Rappi."""
        try:
            item_sel = await self._try_selectors(
                [
                    '[data-testid="product-item"]',
                    '[class*="ProductCard"]',
                    '[class*="product-card"]',
                    'div[class*="item-name"]',
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
            logger.warning(f"[rappi] Error extrayendo precio de {product['name']}: {e}")
            return None

    async def _extract_discounts(self) -> List[str]:
        """Extrae banners y etiquetas de descuento de Rappi."""
        discounts = []
        try:
            promo_sels = [
                '[class*="discount-badge"]',
                '[class*="promotion"]',
                '[class*="offer-tag"]',
                'span[class*="badge"]',
            ]
            for sel in promo_sels:
                els = await self.page.query_selector_all(sel)
                for el in els:
                    text = await el.text_content()
                    if text and len(text.strip()) > 2:
                        discounts.append(text.strip())
        except Exception as e:
            logger.warning(f"[rappi] Error extrayendo descuentos: {e}")
        return list(set(discounts))[:5]

    async def scrape_address(
        self, address: Dict, products: List[Dict]
    ) -> List[ScrapingResult]:
        """Scrapea todos los productos para una dirección en Rappi."""
        results = []

        success = await self._navigate(RAPPI_BASE)
        if not success:
            for product in products:
                r = ScrapingResult(
                    self.PLATFORM_NAME, address, product,
                    status="error", error="No se pudo cargar rappi.com.mx"
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
            logger.info(f"[rappi] Navegando a {restaurant_name} en {address['id']}")

            rest_ok = await self._search_restaurant(restaurant_name)
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
                    r.service_fee = round(price * 0.08, 2)
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
