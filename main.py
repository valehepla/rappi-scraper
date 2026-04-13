"""
main.py — Entry point del sistema de Competitive Intelligence para Rappi.

Uso:
  python main.py                          # Scraping completo (mock por defecto en dev)
  python main.py --live                   # Scraping real con Playwright
  python main.py --platform ubereats      # Solo Uber Eats
  python main.py --platform rappi didifood  # Rappi + DiDi Food
  python main.py --addresses config/addresses.json
  python main.py --report                 # Solo generar informe (sin scraping)
  python main.py --mock                   # Forzar datos mock (para demo)
  python main.py --headful                # Ver el browser (debug)
"""

import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ─── Logging ──────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(open(sys.stdout.fileno(), mode='w', encoding='utf-8', closefd=False)),
        logging.FileHandler(
            f"data/scraping_{datetime.now().strftime('%Y-%m-%d')}.log",
            encoding="utf-8",
        ),
    ],
)
logger = logging.getLogger(__name__)

# Asegurar que la carpeta data existe antes del logging
Path("data").mkdir(exist_ok=True)

# ─── CLI ──────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Rappi Competitive Intelligence Scraper",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  python main.py --mock                     # Demo con datos realistas (recomendado para presentación)
  python main.py --live --platform ubereats # Scraping real de Uber Eats
  python main.py --live                     # Scraping real de todas las plataformas
  python main.py --report                   # Generar informe de la última ejecución
        """,
    )
    parser.add_argument(
        "--platform",
        nargs="+",
        choices=["rappi", "ubereats", "didifood"],
        default=["rappi", "ubereats", "didifood"],
        help="Plataforma(s) a scrapear (default: todas)",
    )
    parser.add_argument(
        "--addresses",
        default="config/addresses.json",
        help="Ruta al archivo JSON de direcciones",
    )
    parser.add_argument(
        "--products",
        default="config/products.json",
        help="Ruta al archivo JSON de productos",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        default=True,
        help="Usar datos mock realistas en lugar de scraping live (default: True)",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Forzar scraping real con Playwright (ignora --mock)",
    )
    parser.add_argument(
        "--headful",
        action="store_true",
        help="Mostrar el browser durante el scraping (útil para debug)",
    )
    parser.add_argument(
        "--report",
        action="store_true",
        help="Generar informe después del scraping (o solo el informe si no hay scraping)",
    )
    parser.add_argument(
        "--only-report",
        action="store_true",
        help="Solo generar informe con datos existentes en data/",
    )
    parser.add_argument(
        "--limit-addresses",
        type=int,
        default=None,
        help="Limitar el número de direcciones (útil para tests rápidos)",
    )
    parser.add_argument(
        "--output",
        default="data",
        help="Directorio de output (default: data/)",
    )
    return parser


# ─── Config loading ───────────────────────────────────────────────────────────

def load_config(addresses_path: str, products_path: str):
    """Carga las configuraciones de direcciones y productos."""
    try:
        with open(addresses_path, encoding="utf-8") as f:
            addresses = json.load(f)
        logger.info(f"Cargadas {len(addresses)} direcciones desde {addresses_path}")
    except FileNotFoundError:
        logger.error(f"No se encontró {addresses_path}")
        sys.exit(1)

    try:
        with open(products_path, encoding="utf-8") as f:
            products = json.load(f)
        logger.info(f"Cargados {len(products)} productos desde {products_path}")
    except FileNotFoundError:
        logger.error(f"No se encontró {products_path}")
        sys.exit(1)

    return addresses, products


# ─── Mock scraping ────────────────────────────────────────────────────────────

def run_mock_scraping(
    platforms: list,
    addresses: list,
    products: list,
    output_dir: str = "data",
) -> list:
    """Genera datos mock realistas para todas las plataformas y direcciones."""
    from scrapers.mock_data import generate_platform_data

    all_results = []
    Path(output_dir).mkdir(exist_ok=True)

    for platform in platforms:
        logger.info(f"Generando datos mock para {platform}...")
        results = generate_platform_data(platform, addresses, products)
        all_results.extend(results)

        # Guardar por plataforma
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
        filepath = Path(output_dir) / f"{platform}_{timestamp}.json"
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        logger.info(f"  -> {len(results)} registros guardados en {filepath}")

    return all_results


# ─── Live scraping ────────────────────────────────────────────────────────────

async def run_live_scraping(
    platforms: list,
    addresses: list,
    products: list,
    headless: bool = True,
    output_dir: str = "data",
) -> list:
    """Ejecuta scraping real con Playwright en todas las plataformas."""
    from scrapers.ubereats import UberEatsScraper
    from scrapers.rappi import RappiScraper
    from scrapers.didifood import DiFoodScraper

    proxy = os.getenv("PROXY_URL")
    if proxy:
        logger.info(f"Usando proxy: {proxy[:30]}...")

    scraper_map = {
        "ubereats": UberEatsScraper,
        "rappi": RappiScraper,
        "didifood": DiFoodScraper,
    }

    all_results = []
    Path(output_dir).mkdir(exist_ok=True)

    for platform in platforms:
        ScraperClass = scraper_map[platform]
        logger.info(f"Iniciando scraping LIVE de {platform}...")

        try:
            async with ScraperClass(headless=headless, proxy=proxy) as scraper:
                results = await scraper.scrape_all(addresses, products)
                all_results.extend(results)

                # Guardar por plataforma
                timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
                filepath = Path(output_dir) / f"{platform}_{timestamp}.json"
                with open(filepath, "w", encoding="utf-8") as f:
                    json.dump(results, f, ensure_ascii=False, indent=2)

                success = sum(1 for r in results if r.get("scrape_status") == "success")
                errors = sum(1 for r in results if r.get("scrape_status") == "error")
                logger.info(
                    f"  → {platform}: {success} éxitos, {errors} errores — "
                    f"guardado en {filepath}"
                )
        except Exception as e:
            logger.error(f"Error fatal en scraper de {platform}: {e}")

    return all_results


# ─── Combined output ──────────────────────────────────────────────────────────

def save_combined_output(all_results: list, output_dir: str = "data"):
    """Guarda todos los resultados en un único archivo combinado."""
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
    filepath = Path(output_dir) / f"combined_{timestamp}.json"

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)

    # También como CSV con pandas
    try:
        import pandas as pd
        df = pd.DataFrame(all_results)
        csv_path = Path(output_dir) / f"combined_{timestamp}.csv"
        df.to_csv(csv_path, index=False, encoding="utf-8")
        logger.info(f"CSV guardado: {csv_path}")
    except ImportError:
        logger.warning("pandas no instalado — solo se guardó JSON")

    logger.info(f"Datos combinados: {filepath} ({len(all_results)} registros totales)")
    return str(filepath)


# ─── Summary ──────────────────────────────────────────────────────────────────

def print_summary(all_results: list):
    """Imprime un resumen de los datos recolectados en la terminal."""
    if not all_results:
        print("\nNo hay datos para resumir.")
        return

    platforms = list(set(r["platform"] for r in all_results))
    cities = list(set(r["city"] for r in all_results if r.get("city")))
    available = [r for r in all_results if r.get("restaurant_available")]

    print("\n" + "=" * 60)
    print("  RESUMEN DEL SCRAPING")
    print("=" * 60)
    print(f"  Total registros    : {len(all_results)}")
    print(f"  Plataformas        : {', '.join(platforms)}")
    print(f"  Ciudades           : {', '.join(sorted(cities))}")
    print(f"  Con datos válidos  : {len(available)} ({100*len(available)//len(all_results)}%)")

    if available:
        try:
            import pandas as pd
            df = pd.DataFrame(available)
            print("\n  Precios promedio por plataforma (Big Mac, MXN):")
            bm = df[df["product_id"] == "bigmac"].groupby("platform")["price_product"].mean()
            for plat, price in bm.items():
                print(f"    {plat:12}: ${price:.2f}")

            print("\n  Delivery fee promedio por plataforma (MXN):")
            fees = df.groupby("platform")["delivery_fee"].mean()
            for plat, fee in fees.items():
                print(f"    {plat:12}: ${fee:.2f}")
        except Exception:
            pass

    print("=" * 60 + "\n")


# ─── Entry point ──────────────────────────────────────────────────────────────

def main():
    parser = build_parser()
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("  Rappi Competitive Intelligence System")
    logger.info(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 60)

    # Solo generar informe
    if args.only_report:
        logger.info("Modo: Solo generar informe")
        from reports.generate_report import ReportGenerator
        gen = ReportGenerator()
        gen.load_data()
        report_path = gen.render_report()
        logger.info(f"Informe generado: {report_path}")
        return

    # Cargar config
    addresses, products = load_config(args.addresses, args.products)

    # Limitar direcciones si se especificó
    if args.limit_addresses:
        addresses = addresses[: args.limit_addresses]
        logger.info(f"Limitado a {len(addresses)} direcciones")

    # Decidir modo de scraping
    use_live = args.live
    if use_live:
        logger.info(
            f"Modo: LIVE scraping — plataformas: {args.platform}"
        )
        all_results = asyncio.run(
            run_live_scraping(
                platforms=args.platform,
                addresses=addresses,
                products=products,
                headless=not args.headful,
                output_dir=args.output,
            )
        )
    else:
        logger.info(
            f"Modo: MOCK — plataformas: {args.platform} "
            f"({len(addresses)} dirs × {len(products)} productos)"
        )
        all_results = run_mock_scraping(
            platforms=args.platform,
            addresses=addresses,
            products=products,
            output_dir=args.output,
        )

    # Guardar output combinado
    if all_results:
        save_combined_output(all_results, output_dir=args.output)
        print_summary(all_results)

    # Generar informe
    if args.report or not use_live:
        logger.info("Generando informe de insights...")
        try:
            from reports.generate_report import ReportGenerator
            gen = ReportGenerator(data_dir=args.output)
            gen.load_data()
            report_path = gen.render_report()
            logger.info(f"Informe generado: {report_path}")
            print(f"\n  Informe disponible en: {report_path}\n")
        except Exception as e:
            logger.error(f"Error generando informe: {e}")

    logger.info("Proceso completado.")


if __name__ == "__main__":
    main()
