"""
Base scraper class con retry logic, rate limiting y soporte para screenshots.
Todos los scrapers de plataforma heredan de esta clase.
"""

import asyncio
import logging
import random
import time
import json
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List, Any

logger = logging.getLogger(__name__)

# User agents reales de Chrome en Windows — rotamos para evitar detección
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0",
]

# Control de rate limiting por dominio (clase-level para compartir entre instancias)
_DOMAIN_LAST_REQUEST: Dict[str, float] = {}
_DOMAIN_LOCK = asyncio.Lock()


class ScrapingResult:
    """Modelo de datos para un resultado de scraping."""

    def __init__(
        self,
        platform: str,
        address: Dict,
        product: Dict,
        status: str = "success",
        error: Optional[str] = None,
    ):
        self.platform = platform
        self.address = address
        self.product = product
        self.timestamp = datetime.now().isoformat()
        self.status = status
        self.error = error

        # Métricas — se llenan durante el scraping
        self.price_product: Optional[float] = None
        self.delivery_fee: Optional[float] = None
        self.service_fee: Optional[float] = None
        self.estimated_delivery_min: Optional[int] = None
        self.estimated_delivery_max: Optional[int] = None
        self.discounts_active: List[str] = []
        self.restaurant_available: bool = True
        self.final_price_total: Optional[float] = None
        self.screenshot_path: Optional[str] = None

    def to_dict(self) -> Dict:
        return {
            "platform": self.platform,
            "timestamp": self.timestamp,
            "scrape_status": self.status,
            "error_message": self.error,
            # Dirección
            "address_id": self.address["id"],
            "city": self.address["city"],
            "zone": self.address["zone"],
            "zone_type": self.address["zone_type"],
            "full_address": self.address["full_address"],
            # Producto
            "product_id": self.product["id"],
            "product_name": self.product["name"],
            "product_category": self.product["category"],
            "restaurant": self.product["restaurant"],
            # Métricas
            "price_product": self.price_product,
            "delivery_fee": self.delivery_fee,
            "service_fee": self.service_fee,
            "estimated_delivery_min": self.estimated_delivery_min,
            "estimated_delivery_max": self.estimated_delivery_max,
            "discounts_active": self.discounts_active,
            "restaurant_available": self.restaurant_available,
            "final_price_total": self.final_price_total,
            "screenshot_path": self.screenshot_path,
        }


class BaseScraper(ABC):
    """
    Clase base para todos los scrapers de plataforma.

    Proporciona:
    - Gestión del browser Playwright con configuración stealth
    - Retry logic con backoff exponencial (máx 3 intentos)
    - Rate limiting mínimo de 2s entre requests por dominio
    - Captura automática de screenshots como evidencia
    - Guardado de resultados en JSON con timestamp
    """

    PLATFORM_NAME: str = "base"
    BASE_DOMAIN: str = ""
    MIN_DELAY: float = 2.0
    MAX_RETRIES: int = 3

    def __init__(self, headless: bool = True, proxy: Optional[str] = None):
        self.headless = headless
        self.proxy = proxy
        self.browser = None
        self.context = None
        self.page = None
        self._playwright = None
        self.screenshots_dir = Path("data/screenshots")
        self.screenshots_dir.mkdir(parents=True, exist_ok=True)
        self._user_agent = random.choice(USER_AGENTS)

    # ─── Context manager ──────────────────────────────────────────────────────

    async def __aenter__(self):
        await self._launch_browser()
        return self

    async def __aexit__(self, *args):
        await self._close_browser()

    # ─── Browser lifecycle ────────────────────────────────────────────────────

    async def _launch_browser(self):
        """Lanza Chromium con configuración anti-detección."""
        from playwright.async_api import async_playwright

        self._playwright = await async_playwright().start()

        launch_args = {
            "headless": self.headless,
            "args": [
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--disable-infobars",
                "--window-size=1280,800",
            ],
        }

        if self.proxy:
            launch_args["proxy"] = {"server": self.proxy}

        self.browser = await self._playwright.chromium.launch(**launch_args)

        self.context = await self.browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent=self._user_agent,
            locale="es-MX",
            timezone_id="America/Mexico_City",
            geolocation={"latitude": 19.4326, "longitude": -99.1332},
            permissions=["geolocation"],
        )

        # Remover señales de automatización que detectan los sitios
        await self.context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
            Object.defineProperty(navigator, 'languages', { get: () => ['es-MX', 'es', 'en-US', 'en'] });
            window.chrome = { runtime: {} };
        """)

        self.page = await self.context.new_page()

        # Interceptar y bloquear recursos innecesarios para mayor velocidad
        await self.page.route(
            "**/*.{png,jpg,jpeg,gif,svg,woff,woff2}",
            lambda route: route.abort()
            if route.request.resource_type in ("image", "font")
            else route.continue_(),
        )

        logger.info(
            f"[{self.PLATFORM_NAME}] Browser lanzado — headless={self.headless}"
        )

    async def _close_browser(self):
        """Cierra todos los recursos del browser."""
        try:
            if self.page:
                await self.page.close()
            if self.context:
                await self.context.close()
            if self.browser:
                await self.browser.close()
            if self._playwright:
                await self._playwright.stop()
            logger.info(f"[{self.PLATFORM_NAME}] Browser cerrado correctamente")
        except Exception as e:
            logger.warning(f"[{self.PLATFORM_NAME}] Error al cerrar browser: {e}")

    # ─── Rate limiting ────────────────────────────────────────────────────────

    async def _rate_limit(self):
        """Espera el tiempo necesario para respetar el rate limit del dominio."""
        async with _DOMAIN_LOCK:
            now = time.time()
            last = _DOMAIN_LAST_REQUEST.get(self.BASE_DOMAIN, 0)
            wait = self.MIN_DELAY - (now - last)
            if wait > 0:
                jitter = random.uniform(0.3, 1.2)  # jitter para parecer humano
                await asyncio.sleep(wait + jitter)
            _DOMAIN_LAST_REQUEST[self.BASE_DOMAIN] = time.time()

    # ─── Navigation ───────────────────────────────────────────────────────────

    async def _navigate(self, url: str, wait_until: str = "networkidle") -> bool:
        """Navega a una URL con retry logic y rate limiting."""
        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                await self._rate_limit()
                await self.page.goto(url, wait_until=wait_until, timeout=45_000)
                logger.info(f"[{self.PLATFORM_NAME}] Navegó a: {url}")
                return True
            except Exception as e:
                logger.warning(
                    f"[{self.PLATFORM_NAME}] Intento {attempt}/{self.MAX_RETRIES} "
                    f"falló para {url}: {e}"
                )
                if attempt < self.MAX_RETRIES:
                    backoff = 2**attempt + random.uniform(0, 1)
                    logger.info(f"[{self.PLATFORM_NAME}] Reintentando en {backoff:.1f}s...")
                    await asyncio.sleep(backoff)

        logger.error(
            f"[{self.PLATFORM_NAME}] Falló definitivamente después de "
            f"{self.MAX_RETRIES} intentos: {url}"
        )
        return False

    async def _wait_and_click(self, selector: str, timeout: int = 10_000) -> bool:
        """Espera a que un elemento esté disponible y hace click con retry."""
        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                await self.page.wait_for_selector(selector, timeout=timeout)
                await self.page.click(selector)
                await asyncio.sleep(random.uniform(0.5, 1.5))  # pausa humana
                return True
            except Exception as e:
                logger.warning(
                    f"[{self.PLATFORM_NAME}] click en '{selector}' intento {attempt}: {e}"
                )
                if attempt < self.MAX_RETRIES:
                    await asyncio.sleep(2**attempt)
        return False

    async def _type_slowly(self, selector: str, text: str):
        """Escribe texto con delays aleatorios para simular escritura humana."""
        await self.page.click(selector)
        await asyncio.sleep(0.3)
        for char in text:
            await self.page.keyboard.type(char)
            await asyncio.sleep(random.uniform(0.05, 0.18))

    # ─── Screenshots ──────────────────────────────────────────────────────────

    async def _screenshot(self, label: str) -> Optional[str]:
        """Toma screenshot y lo guarda como evidencia."""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = self.screenshots_dir / f"{self.PLATFORM_NAME}_{label}_{timestamp}.png"
            await self.page.screenshot(path=str(filename), full_page=False)
            logger.info(f"[{self.PLATFORM_NAME}] Screenshot: {filename}")
            return str(filename)
        except Exception as e:
            logger.warning(f"[{self.PLATFORM_NAME}] Error en screenshot: {e}")
            return None

    # ─── Output ───────────────────────────────────────────────────────────────

    def save_results(self, results: List[Dict]) -> str:
        """Guarda resultados en JSON con timestamp en el nombre."""
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
        output_dir = Path("data")
        output_dir.mkdir(exist_ok=True)
        filename = output_dir / f"{self.PLATFORM_NAME}_{timestamp}.json"

        with open(filename, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)

        logger.info(
            f"[{self.PLATFORM_NAME}] {len(results)} registros guardados en {filename}"
        )
        return str(filename)

    # ─── Abstract interface ───────────────────────────────────────────────────

    @abstractmethod
    async def scrape_address(
        self, address: Dict, products: List[Dict]
    ) -> List[ScrapingResult]:
        """
        Scrapea todos los productos para una dirección específica.
        Debe implementarse en cada subclase.
        """
        pass

    async def scrape_all(
        self, addresses: List[Dict], products: List[Dict]
    ) -> List[Dict]:
        """
        Orquesta el scraping de todas las direcciones y productos.
        Maneja errores por dirección sin abortar el proceso completo.
        """
        all_results = []
        total = len(addresses)

        for i, address in enumerate(addresses, 1):
            logger.info(
                f"[{self.PLATFORM_NAME}] Procesando dirección {i}/{total}: "
                f"{address['id']} ({address['city']})"
            )
            try:
                results = await self.scrape_address(address, products)
                for r in results:
                    all_results.append(r.to_dict())
                logger.info(
                    f"[{self.PLATFORM_NAME}] OK {address['id']}: "
                    f"{len(results)} productos scrapeados"
                )
            except Exception as e:
                logger.error(
                    f"[{self.PLATFORM_NAME}] ERROR en {address['id']}: {e}"
                )
                # Registrar el fallo como resultado con status="error"
                for product in products:
                    r = ScrapingResult(
                        self.PLATFORM_NAME, address, product,
                        status="error", error=str(e)
                    )
                    all_results.append(r.to_dict())

            # Pausa entre direcciones
            if i < total:
                await asyncio.sleep(random.uniform(1.5, 4.0))

        return all_results
