"""
Tests básicos del sistema de scraping.

Cubren:
  - Generación de datos mock (estructura y valores)
  - Carga de configuración (addresses, products)
  - Pipeline de reporte (carga de datos, cálculo de KPIs)

Ejecutar:
  python -m pytest tests/ -v
"""

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

# Asegurar imports desde el root del proyecto
sys.path.insert(0, str(Path(__file__).parent.parent))

from scrapers.mock_data import generate_record, generate_platform_data, PLATFORM_CONFIG


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def sample_address():
    return {
        "id": "cdmx_polanco",
        "city": "CDMX",
        "zone": "polanco",
        "zone_type": "high_income",
        "full_address": "Av. Presidente Masaryk 61, Polanco, CDMX",
        "lat": 19.4326,
        "lng": -99.1936,
        "notes": "Test address",
    }


@pytest.fixture
def sample_product():
    return {
        "id": "bigmac",
        "name": "Big Mac",
        "category": "fast_food",
        "restaurant": "McDonald's",
        "search_terms": ["Big Mac"],
        "reference_price_mxn": 95,
    }


@pytest.fixture
def all_addresses():
    with open("config/addresses.json", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def all_products():
    with open("config/products.json", encoding="utf-8") as f:
        return json.load(f)


# ─── Tests de configuración ───────────────────────────────────────────────────

class TestConfig:
    def test_addresses_file_exists(self):
        assert Path("config/addresses.json").exists()

    def test_products_file_exists(self):
        assert Path("config/products.json").exists()

    def test_addresses_count(self, all_addresses):
        """Debe haber entre 20 y 50 direcciones."""
        assert 20 <= len(all_addresses) <= 50, f"Se esperan 20-50 direcciones, hay {len(all_addresses)}"

    def test_addresses_required_fields(self, all_addresses):
        required = {"id", "city", "zone", "zone_type", "full_address"}
        for addr in all_addresses:
            missing = required - set(addr.keys())
            assert not missing, f"Dirección {addr.get('id')} falta campos: {missing}"

    def test_addresses_cities_coverage(self, all_addresses):
        """Debe cubrir al menos CDMX, Guadalajara y Monterrey."""
        cities = {a["city"] for a in all_addresses}
        assert "CDMX" in cities
        assert "Guadalajara" in cities
        assert "Monterrey" in cities

    def test_products_count(self, all_products):
        assert len(all_products) >= 3, "Se esperan al menos 3 productos de referencia"

    def test_products_required_fields(self, all_products):
        required = {"id", "name", "category", "restaurant", "reference_price_mxn"}
        for prod in all_products:
            missing = required - set(prod.keys())
            assert not missing, f"Producto {prod.get('id')} falta campos: {missing}"


# ─── Tests de mock data ───────────────────────────────────────────────────────

class TestMockData:
    PLATFORMS = list(PLATFORM_CONFIG.keys())

    def test_generate_record_structure(self, sample_address, sample_product):
        """El registro generado debe tener todos los campos requeridos."""
        required_fields = {
            "platform", "timestamp", "scrape_status",
            "address_id", "city", "zone", "zone_type",
            "product_id", "product_name", "product_category", "restaurant",
            "delivery_fee", "estimated_delivery_min", "estimated_delivery_max",
            "discounts_active", "restaurant_available", "final_price_total",
        }
        for platform in self.PLATFORMS:
            record = generate_record(platform, sample_address, sample_product, seed=42)
            missing = required_fields - set(record.keys())
            assert not missing, f"[{platform}] Faltan campos: {missing}"

    def test_record_values_are_realistic(self, sample_address, sample_product):
        """Los valores generados deben ser realistas."""
        for platform in self.PLATFORMS:
            r = generate_record(platform, sample_address, sample_product, seed=42)
            if not r["restaurant_available"]:
                continue

            # Precio Big Mac entre $70 y $180 MXN
            assert 70 <= r["price_product"] <= 180, (
                f"[{platform}] Precio fuera de rango: {r['price_product']}"
            )

            # Delivery fee entre $0 y $80 MXN
            assert 0 <= r["delivery_fee"] <= 80, (
                f"[{platform}] Delivery fee fuera de rango: {r['delivery_fee']}"
            )

            # ETA entre 10 y 70 minutos
            assert 10 <= r["estimated_delivery_min"] <= 70, (
                f"[{platform}] ETA mín fuera de rango: {r['estimated_delivery_min']}"
            )
            assert r["estimated_delivery_min"] <= r["estimated_delivery_max"], (
                f"[{platform}] ETA mín > máx"
            )

            # Precio total debe ser mayor que el precio del producto
            assert r["final_price_total"] >= r["price_product"], (
                f"[{platform}] Precio total menor que precio del producto"
            )

    def test_mock_data_reproducibility(self, sample_address, sample_product):
        """Los mismos seeds deben producir los mismos datos."""
        r1 = generate_record("rappi", sample_address, sample_product, seed=123)
        r2 = generate_record("rappi", sample_address, sample_product, seed=123)
        assert r1["price_product"] == r2["price_product"]
        assert r1["delivery_fee"] == r2["delivery_fee"]

    def test_generate_platform_data_volume(self, all_addresses, all_products):
        """Debe generar n_addresses × n_products registros por plataforma."""
        for platform in self.PLATFORMS:
            results = generate_platform_data(platform, all_addresses, all_products)
            expected = len(all_addresses) * len(all_products)
            assert len(results) == expected, (
                f"[{platform}] Se esperaban {expected} registros, se generaron {len(results)}"
            )

    def test_didi_more_free_delivery_in_gdl(self, all_addresses, all_products):
        """DiDi Food debe tener mayor tasa de envío gratis en Guadalajara."""
        gdl_addresses = [a for a in all_addresses if a["city"] == "Guadalajara"]
        if not gdl_addresses:
            pytest.skip("No hay direcciones de Guadalajara en el config")

        for platform in ["rappi", "didifood"]:
            results = generate_platform_data(platform, gdl_addresses, all_products[:1])
            free_rate = sum(
                1 for r in results
                if r.get("restaurant_available") and r.get("delivery_fee") == 0
            ) / len(results)

            if platform == "didifood":
                assert free_rate > 0.4, (
                    f"DiDi Food en GDL debe tener >40% envío gratis, tiene {free_rate:.0%}"
                )
            elif platform == "rappi":
                assert free_rate < 0.3, (
                    f"Rappi en GDL debe tener <30% envío gratis, tiene {free_rate:.0%}"
                )

    def test_didifood_lower_fees_in_suburban(self, all_addresses, all_products):
        """DiDi debe tener fees menores que Rappi en zonas suburbanas."""
        suburban = [
            a for a in all_addresses
            if a["zone_type"] in ("suburban", "popular_suburban")
        ]
        if not suburban:
            pytest.skip("No hay zonas suburbanas en el config")

        product = all_products[0]
        rappi_fees = [
            r["delivery_fee"] for r in generate_platform_data("rappi", suburban, [product])
            if r.get("restaurant_available") and r.get("delivery_fee") is not None
        ]
        didi_fees = [
            r["delivery_fee"] for r in generate_platform_data("didifood", suburban, [product])
            if r.get("restaurant_available") and r.get("delivery_fee") is not None
        ]

        avg_rappi = sum(rappi_fees) / len(rappi_fees)
        avg_didi = sum(didi_fees) / len(didi_fees)

        assert avg_didi < avg_rappi, (
            f"DiDi (${avg_didi:.1f}) debe ser más barato que Rappi (${avg_rappi:.1f}) "
            "en zonas suburbanas"
        )


# ─── Tests del pipeline de reporte ───────────────────────────────────────────

class TestReportPipeline:
    def test_report_generates_from_mock_data(self, all_addresses, all_products):
        """El pipeline completo (mock → JSON → reporte) debe funcionar sin errores."""
        from scrapers.mock_data import generate_platform_data
        from reports.generate_report import ReportGenerator

        with tempfile.TemporaryDirectory() as tmpdir:
            # Generar datos mock
            all_records = []
            for platform in ["rappi", "ubereats", "didifood"]:
                records = generate_platform_data(platform, all_addresses[:5], all_products)
                all_records.extend(records)

                # Guardar en el tmp dir
                filepath = Path(tmpdir) / f"{platform}_test.json"
                with open(filepath, "w") as f:
                    json.dump(records, f)

            # Generar reporte
            gen = ReportGenerator(data_dir=tmpdir)
            gen.load_data()

            assert gen.df is not None
            assert len(gen.df) > 0

            kpis = gen.compute_kpis()
            assert "bigmac_prices" in kpis
            assert "avg_delivery_fee" in kpis
            assert "avg_eta" in kpis

            insights = gen.generate_insights()
            assert len(insights) == 5

            output_path = Path(tmpdir) / "test_report.html"
            gen.render_report(str(output_path))
            assert output_path.exists()
            assert output_path.stat().st_size > 10_000  # al menos 10KB
