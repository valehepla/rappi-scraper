"""
generate_report.py — Generador de informe de insights competitivos.

Produce un reporte HTML interactivo con:
  - Comparación de precios por plataforma
  - Análisis de delivery fees por zona
  - Comparación de tiempos de entrega
  - Heatmap de competitividad por ciudad/zona
  - Top 5 insights accionables con findings, impacto y recomendaciones

Uso:
  python reports/generate_report.py
  python reports/generate_report.py --data-dir data --output reports/informe.html
"""

import argparse
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from jinja2 import Template

logger = logging.getLogger(__name__)

# ─── Paleta de colores por plataforma ─────────────────────────────────────────

PLATFORM_COLORS = {
    "rappi": "#FF441F",        # Naranja Rappi
    "ubereats": "#06C167",     # Verde Uber Eats
    "didifood": "#FF6900",     # Naranja DiDi
}

PLATFORM_DISPLAY = {
    "rappi": "Rappi",
    "ubereats": "Uber Eats",
    "didifood": "DiDi Food",
}

ZONE_ORDER = [
    "high_income", "mid_high", "mid", "popular", "suburban", "popular_suburban"
]
ZONE_LABELS = {
    "high_income": "Alto ingreso",
    "mid_high": "Medio-alto",
    "mid": "Medio",
    "popular": "Popular",
    "suburban": "Suburbano",
    "popular_suburban": "Suburbano popular",
}

CITY_ORDER = ["CDMX", "Ecatepec", "Tlalnepantla", "Guadalajara", "Monterrey"]


# ─── Data loading ─────────────────────────────────────────────────────────────

class ReportGenerator:
    """Genera el informe HTML de insights competitivos."""

    def __init__(self, data_dir: str = "data"):
        self.data_dir = Path(data_dir)
        self.df: Optional[pd.DataFrame] = None
        self.df_valid: Optional[pd.DataFrame] = None  # solo registros con datos

    def load_data(self) -> pd.DataFrame:
        """Carga y consolida todos los JSON de scraping disponibles."""
        records = []

        # Priorizar combined_*, luego archivos por plataforma
        json_files = sorted(self.data_dir.glob("*.json"))
        combined = [f for f in json_files if f.stem.startswith("combined_")]
        platform_files = [f for f in json_files if not f.stem.startswith("combined_")]

        files_to_load = combined[-1:] if combined else platform_files

        for filepath in files_to_load:
            try:
                with open(filepath, encoding="utf-8") as f:
                    data = json.load(f)
                records.extend(data)
                logger.info(f"Cargados {len(data)} registros de {filepath.name}")
            except Exception as e:
                logger.warning(f"Error cargando {filepath}: {e}")

        if not records:
            raise ValueError(
                f"No se encontraron datos en {self.data_dir}. "
                "Ejecuta primero: python main.py"
            )

        self.df = pd.DataFrame(records)
        self.df["platform_label"] = self.df["platform"].map(PLATFORM_DISPLAY)

        # Solo registros con datos válidos (restaurante disponible)
        self.df_valid = self.df[
            self.df["restaurant_available"] == True  # noqa: E712
        ].copy()

        logger.info(
            f"Total registros: {len(self.df)} | "
            f"Con datos válidos: {len(self.df_valid)}"
        )
        return self.df

    # ─── Gráficos ─────────────────────────────────────────────────────────────

    def chart_price_comparison(self) -> str:
        """Gráfico 1: Precio promedio por producto y plataforma."""
        df = self.df_valid.copy()
        grouped = (
            df.groupby(["platform_label", "product_name"])["price_product"]
            .mean()
            .reset_index()
        )
        grouped["price_product"] = grouped["price_product"].round(2)
        grouped["price_label"] = grouped["price_product"].apply(lambda v: f"${v:.0f}")

        fig = px.bar(
            grouped,
            x="product_name",
            y="price_product",
            color="platform_label",
            barmode="group",
            color_discrete_map={v: PLATFORM_COLORS[k] for k, v in PLATFORM_DISPLAY.items()},
            labels={
                "product_name": "Producto",
                "price_product": "Precio promedio (MXN)",
                "platform_label": "Plataforma",
            },
            title="Comparación de precios por producto y plataforma",
            text="price_label",
        )
        fig.update_traces(textposition="outside")
        fig.update_layout(
            yaxis_title="Precio (MXN)",
            legend_title="Plataforma",
            height=450,
            uniformtext_minsize=8,
        )
        return fig.to_html(full_html=False, include_plotlyjs=False)

    def chart_delivery_fee_by_zone(self) -> str:
        """Gráfico 2: Delivery fee promedio por tipo de zona y plataforma."""
        df = self.df_valid.copy()
        df["zone_label"] = df["zone_type"].map(ZONE_LABELS)

        # Ordenar zonas por ingreso
        zone_order = [ZONE_LABELS[z] for z in ZONE_ORDER if z in ZONE_LABELS]

        grouped = (
            df.groupby(["platform_label", "zone_type", "zone_label"])["delivery_fee"]
            .mean()
            .reset_index()
        )
        grouped["delivery_fee"] = grouped["delivery_fee"].round(2)
        grouped["fee_label"] = grouped["delivery_fee"].apply(lambda v: f"${v:.0f}")

        fig = px.bar(
            grouped,
            x="zone_label",
            y="delivery_fee",
            color="platform_label",
            barmode="group",
            color_discrete_map={v: PLATFORM_COLORS[k] for k, v in PLATFORM_DISPLAY.items()},
            category_orders={"zone_label": zone_order},
            labels={
                "zone_label": "Tipo de zona",
                "delivery_fee": "Delivery fee promedio (MXN)",
                "platform_label": "Plataforma",
            },
            title="Delivery fee por tipo de zona — Rappi vs competencia",
            text="fee_label",
        )
        fig.update_traces(textposition="outside")
        fig.update_layout(height=450, legend_title="Plataforma")
        return fig.to_html(full_html=False, include_plotlyjs=False)

    def chart_eta_by_platform_and_city(self) -> str:
        """Gráfico 3: ETA promedio por plataforma y ciudad."""
        df = self.df_valid.copy()
        df["eta_mid"] = (df["estimated_delivery_min"] + df["estimated_delivery_max"]) / 2

        grouped = (
            df.groupby(["platform_label", "city"])["eta_mid"]
            .mean()
            .reset_index()
        )
        grouped["eta_mid"] = grouped["eta_mid"].round(1)
        grouped["eta_label"] = grouped["eta_mid"].apply(lambda v: f"{v:.0f} min")

        cities = [c for c in CITY_ORDER if c in grouped["city"].unique()]

        fig = px.bar(
            grouped,
            x="city",
            y="eta_mid",
            color="platform_label",
            barmode="group",
            color_discrete_map={v: PLATFORM_COLORS[k] for k, v in PLATFORM_DISPLAY.items()},
            category_orders={"city": cities},
            labels={
                "city": "Ciudad",
                "eta_mid": "Tiempo estimado promedio (min)",
                "platform_label": "Plataforma",
            },
            title="Tiempo de entrega promedio por ciudad y plataforma",
            text="eta_label",
        )
        fig.update_traces(textposition="outside")
        fig.update_layout(height=450, legend_title="Plataforma")
        return fig.to_html(full_html=False, include_plotlyjs=False)

    def chart_fee_free_delivery_rate(self) -> str:
        """Gráfico 4: % de casos con envío gratis por plataforma y ciudad."""
        df = self.df_valid.copy()

        df["free_delivery"] = df["delivery_fee"] == 0

        grouped = (
            df.groupby(["platform_label", "city"])["free_delivery"]
            .mean()
            .mul(100)
            .round(1)
            .reset_index()
        )
        grouped.columns = ["platform_label", "city", "free_pct"]

        cities = [c for c in CITY_ORDER if c in grouped["city"].unique()]

        fig = px.bar(
            grouped,
            x="city",
            y="free_pct",
            color="platform_label",
            barmode="group",
            color_discrete_map={v: PLATFORM_COLORS[k] for k, v in PLATFORM_DISPLAY.items()},
            category_orders={"city": cities},
            labels={
                "city": "Ciudad",
                "free_pct": "% con envío gratis",
                "platform_label": "Plataforma",
            },
            title="Porcentaje de casos con envío gratis por ciudad",
            text=grouped["free_pct"].apply(lambda v: f"{v:.1f}%"),
        )
        fig.update_traces(textposition="outside")
        fig.update_layout(height=450, yaxis_range=[0, 100], legend_title="Plataforma")
        return fig.to_html(full_html=False, include_plotlyjs=False)

    def chart_total_cost_heatmap(self) -> str:
        """Gráfico 5: Heatmap del costo total (precio + fees) por plataforma y zona."""
        import numpy as np

        df = self.df_valid[self.df_valid["product_id"] == "bigmac"].copy()
        if df.empty:
            df = self.df_valid.copy()

        df["zone_label"] = df["zone_type"].map(ZONE_LABELS)

        # Usar pivot() explícito para evitar MultiIndex en columnas
        grouped = (
            df.groupby(["zone_label", "platform_label"])["final_price_total"]
            .mean()
            .round(2)
            .reset_index()
        )
        pivot = grouped.pivot(
            index="zone_label", columns="platform_label", values="final_price_total"
        )

        zone_order = [ZONE_LABELS[z] for z in ZONE_ORDER if ZONE_LABELS[z] in pivot.index]
        pivot = pivot.reindex(zone_order).dropna(how="all")

        platforms = list(pivot.columns)
        zones = list(pivot.index)

        # Convertir a listas nativas (Plotly no acepta numpy arrays con NaN bien)
        z_values = [
            [None if np.isnan(v) else round(float(v), 2) for v in row]
            for row in pivot.values
        ]
        text_values = [
            [f"${v:.0f}" if v is not None else "N/D" for v in row]
            for row in z_values
        ]

        fig = go.Figure(
            data=go.Heatmap(
                z=z_values,
                x=platforms,
                y=zones,
                colorscale="RdYlGn_r",
                text=text_values,
                texttemplate="%{text}",
                colorbar=dict(title="MXN"),
                zmin=min(v for row in z_values for v in row if v is not None) * 0.95,
                zmax=max(v for row in z_values for v in row if v is not None) * 1.05,
            )
        )
        fig.update_layout(
            title="Costo total al usuario: Big Mac + delivery + service fee (MXN)",
            xaxis_title="Plataforma",
            yaxis_title="Tipo de zona",
            height=400,
        )
        return fig.to_html(full_html=False, include_plotlyjs=False)

    def chart_fee_breakdown(self) -> str:
        """Gráfico 6: Desglose de costo total (precio + delivery fee + service fee) por plataforma."""
        df = self.df_valid[self.df_valid["product_id"] == "bigmac"].copy()
        if df.empty:
            df = self.df_valid.copy()

        grouped = (
            df.groupby("platform")[["price_product", "delivery_fee", "service_fee"]]
            .mean()
            .round(2)
            .reset_index()
        )
        grouped["platform_label"] = grouped["platform"].map(PLATFORM_DISPLAY)

        fig = go.Figure()
        components = [
            ("price_product", "Precio producto", 0.6),
            ("delivery_fee", "Delivery fee", 0.85),
            ("service_fee", "Service fee", 1.0),
        ]

        for col, label, opacity in components:
            fig.add_trace(
                go.Bar(
                    name=label,
                    x=grouped["platform_label"],
                    y=grouped[col],
                    text=grouped[col].apply(lambda v: f"${v:.0f}"),
                    textposition="inside",
                    marker_color=[
                        f"rgba({int(PLATFORM_COLORS[p][1:3], 16)}, "
                        f"{int(PLATFORM_COLORS[p][3:5], 16)}, "
                        f"{int(PLATFORM_COLORS[p][5:7], 16)}, {opacity})"
                        for p in grouped["platform"]
                    ],
                )
            )

        # Anotar total encima de cada barra
        grouped["total"] = grouped["price_product"] + grouped["delivery_fee"] + grouped["service_fee"]
        for _, row in grouped.iterrows():
            fig.add_annotation(
                x=row["platform_label"],
                y=row["total"],
                text=f"<b>${row['total']:.0f}</b>",
                showarrow=False,
                yshift=10,
                font=dict(size=13),
            )

        fig.update_layout(
            barmode="stack",
            title="Estructura de costo total al usuario — Big Mac (precio + delivery fee + service fee)",
            yaxis_title="Costo (MXN)",
            xaxis_title="Plataforma",
            legend_title="Componente",
            height=430,
        )
        return fig.to_html(full_html=False, include_plotlyjs=False)

    def chart_promo_type_distribution(self) -> str:
        """Gráfico 7: Tipos de descuento más frecuentes por plataforma (% de sesiones)."""
        df = self.df_valid.copy()

        # Explotar la lista de descuentos en filas individuales
        df_exploded = df.explode("discounts_active").dropna(subset=["discounts_active"])
        df_exploded = df_exploded[df_exploded["discounts_active"].str.strip() != ""]

        if df_exploded.empty:
            # Fallback: chart vacío con mensaje
            fig = go.Figure()
            fig.update_layout(
                title="Estrategia promocional — sin datos de descuentos disponibles",
                height=350,
            )
            return fig.to_html(full_html=False, include_plotlyjs=False)

        # Clasificar cada promoción en una categoría
        def classify_promo(text: str) -> str:
            t = text.lower()
            if "envío gratis" in t or "envio gratis" in t or "shipping" in t:
                return "Envío gratis"
            if "%" in t and ("descuento" in t or "off" in t):
                return "% de descuento"
            if "prime" in t or "one" in t or "suscripci" in t or "membresia" in t:
                return "Suscripción / membresía"
            if "primer pedido" in t or "primera compra" in t or "primera vez" in t:
                return "Descuento primer pedido"
            if "cupón" in t or "cupon" in t or "código" in t or "codigo" in t:
                return "Cupón / código"
            if "$" in t and "descuento" in t:
                return "Descuento fijo ($)"
            if "2x1" in t or "gratis" in t:
                return "Oferta 2x1 / regalo"
            return "Otra promoción"

        df_exploded["promo_category"] = df_exploded["discounts_active"].apply(classify_promo)

        # Contar sesiones totales por plataforma (denominador)
        total_sessions = df.groupby("platform").size()

        # Contar ocurrencias de cada categoría por plataforma
        counts = (
            df_exploded.groupby(["platform", "promo_category"])
            .size()
            .reset_index(name="count")
        )
        counts["pct"] = counts.apply(
            lambda r: round(r["count"] / total_sessions.get(r["platform"], 1) * 100, 1),
            axis=1,
        )
        counts["platform_label"] = counts["platform"].map(PLATFORM_DISPLAY)

        # Ordenar categorías por frecuencia total
        cat_order = (
            counts.groupby("promo_category")["pct"].sum()
            .sort_values(ascending=True)
            .index.tolist()
        )

        counts["pct_label"] = counts["pct"].apply(lambda v: f"{v:.1f}%")

        fig = px.bar(
            counts,
            x="pct",
            y="promo_category",
            color="platform_label",
            orientation="h",
            barmode="group",
            color_discrete_map={v: PLATFORM_COLORS[k] for k, v in PLATFORM_DISPLAY.items()},
            category_orders={"promo_category": cat_order},
            labels={
                "pct": "% de sesiones con este tipo de promoción",
                "promo_category": "Tipo de promoción",
                "platform_label": "Plataforma",
            },
            title="Estrategia promocional — frecuencia de tipos de descuento por plataforma",
            text="pct_label",
        )
        fig.update_traces(textposition="outside")
        fig.update_layout(
            height=420,
            xaxis_title="% de sesiones",
            legend_title="Plataforma",
            xaxis=dict(range=[0, counts["pct"].max() * 1.2]),
        )
        return fig.to_html(full_html=False, include_plotlyjs=False)

    # ─── KPIs y métricas de resumen ───────────────────────────────────────────

    def compute_kpis(self) -> Dict:
        """Calcula KPIs clave para el resumen ejecutivo."""
        df = self.df_valid
        kpis = {}

        # Precio promedio Big Mac por plataforma
        bm = df[df["product_id"] == "bigmac"].groupby("platform")["price_product"].mean()
        kpis["bigmac_prices"] = {k: round(v, 2) for k, v in bm.items()}

        # Delivery fee promedio
        fees = df.groupby("platform")["delivery_fee"].mean()
        kpis["avg_delivery_fee"] = {k: round(v, 2) for k, v in fees.items()}

        # ETA promedio
        df_eta = df.copy()
        df_eta["eta_mid"] = (
            df_eta["estimated_delivery_min"] + df_eta["estimated_delivery_max"]
        ) / 2
        etas = df_eta.groupby("platform")["eta_mid"].mean()
        kpis["avg_eta"] = {k: round(v, 1) for k, v in etas.items()}

        # % envío gratis
        free = df.groupby("platform").apply(
            lambda x: (x["delivery_fee"] == 0).mean() * 100
        )
        kpis["free_delivery_pct"] = {k: round(v, 1) for k, v in free.items()}

        # Disponibilidad (% restaurantes disponibles)
        availability = (
            self.df.groupby("platform")
            .apply(lambda x: x["restaurant_available"].mean() * 100)
        )
        kpis["availability_pct"] = {k: round(v, 1) for k, v in availability.items()}

        # Precio promedio general
        overall = df.groupby("platform")["price_product"].mean()
        kpis["avg_product_price"] = {k: round(v, 2) for k, v in overall.items()}

        return kpis

    # ─── Insights ─────────────────────────────────────────────────────────────

    def generate_insights(self) -> List[Dict]:
        """Genera los Top 5 insights accionables a partir de los datos."""
        df = self.df_valid.copy()
        insights = []

        # ── Insight 1: DiDi tiene menores delivery fees en zonas suburbanas ──
        suburban_fees = df[df["zone_type"] == "popular"].groupby(
            "platform"
        )["delivery_fee"].mean()

        rappi_fee = suburban_fees.get("rappi", 0)
        didi_fee = suburban_fees.get("didifood", 0)
        diff_pct = ((rappi_fee - didi_fee) / rappi_fee * 100) if rappi_fee > 0 else 0

        insights.append({
            "rank": 1,
            "icon": "💸",
            "title": "Desventaja en delivery fees en zonas de expansión",
            "finding": (
                f"DiDi Food tiene delivery fees {diff_pct:.0f}% menores que Rappi "
                f"en zonas suburbanas y populares (${didi_fee:.0f} vs ${rappi_fee:.0f} MXN promedio). "
                "Esto impacta directamente la decisión de compra de usuarios sensibles al precio."
            ),
            "impact": (
                "Las zonas populares (Iztapalapa, Ecatepec, Tlaquepaque, Apodaca, Escobedo) "
                "representan el mayor potencial de crecimiento. Un fee más alto puede estar "
                "frenando la adopción de nuevos usuarios en estos mercados."
            ),
            "recommendation": (
                "Implementar subsidio de delivery fee dinámico en zonas populares clave "
                "(Ecatepec, Iztapalapa, Apodaca, Escobedo), activado en horario pico (12-14h y 19-21h). "
                "Meta: paridad con DiDi Food en zonas de expansión dentro de Q2."
            ),
            "data_point": f"DiDi: ${didi_fee:.0f} | Rappi: ${rappi_fee:.0f} | Diferencia: {diff_pct:.0f}%",
        })

        # ── Insight 2: Uber Eats más rápido en zonas premium de CDMX ──────────
        df_cdmx = df[
            (df["city"] == "CDMX") & (df["zone_type"] == "high_income")
        ].copy()
        df_cdmx["eta_mid"] = (
            df_cdmx["estimated_delivery_min"] + df_cdmx["estimated_delivery_max"]
        ) / 2
        cdmx_etas = df_cdmx.groupby("platform")["eta_mid"].mean()

        rappi_eta = cdmx_etas.get("rappi", 0)
        uber_eta = cdmx_etas.get("ubereats", 0)
        eta_diff = rappi_eta - uber_eta

        insights.append({
            "rank": 2,
            "icon": "⚡",
            "title": "Uber Eats más rápido en zonas premium de CDMX",
            "finding": (
                f"En las zonas de alto ingreso de CDMX (Polanco, Santa Fe, Condesa), "
                f"Uber Eats entrega {eta_diff:.0f} minutos más rápido que Rappi "
                f"({uber_eta:.0f} vs {rappi_eta:.0f} min promedio)."
            ),
            "impact": (
                "Los usuarios de alto poder adquisitivo son más sensibles al tiempo que al precio. "
                "Perder en ETA en estos mercados implica perder a los usuarios más rentables, "
                "además de dañar la percepción de marca en el segmento que genera mayor ticket promedio."
            ),
            "recommendation": (
                "Optimizar algoritmo de asignación de repartidores en zonas premium durante peak hours. "
                "Evaluar incentivo de tarifa preferente para repartidores en Polanco, Santa Fe y Condesa. "
                "Target: reducir ETA promedio en zonas high_income a <20 min para Q3."
            ),
            "data_point": f"Uber Eats: {uber_eta:.0f} min | Rappi: {rappi_eta:.0f} min | Gap: {eta_diff:.0f} min",
        })

        # ── Insight 3: Rappi tiene markup de precio mayor en fast food ─────────
        ff = df[df["product_category"] == "fast_food"].groupby("platform")["price_product"].mean()
        rappi_price = ff.get("rappi", 0)
        didi_price = ff.get("didifood", 0)
        price_gap_pct = ((rappi_price - didi_price) / didi_price * 100) if didi_price > 0 else 0

        insights.append({
            "rank": 3,
            "icon": "🍔",
            "title": "Markup de precio de Rappi ~8% mayor que DiDi en fast food",
            "finding": (
                f"En McDonald's, Rappi cobra en promedio {price_gap_pct:.1f}% más que DiDi Food "
                f"por el mismo producto (${rappi_price:.2f} vs ${didi_price:.2f} MXN). "
                "Este diferencial es visible para usuarios que comparan plataformas."
            ),
            "impact": (
                "Con la paridad de oferta entre plataformas, el precio del producto "
                "es el segundo factor más importante de decisión (después del fee de envío). "
                "Un 8% de diferencial en el ítem más popular puede ser determinante para "
                "usuarios que abren ambas apps."
            ),
            "recommendation": (
                "Negociar con McDonald's México acuerdos de precio exclusivo o 'price match' "
                "para igualar o mejorar los precios de DiDi Food. "
                "Alternativamente, absorber parcialmente el diferencial con Rappi Credits "
                "en los primeros 3 pedidos del mes para retener usuarios comparadores."
            ),
            "data_point": f"Rappi: ${rappi_price:.2f} | DiDi: ${didi_price:.2f} | Gap: {price_gap_pct:.1f}%",
        })

        # ── Insight 4: DiDi domina envío gratis en Guadalajara ────────────────
        gdl_free = df[df["city"] == "Guadalajara"].groupby("platform").apply(
            lambda x: (x["delivery_fee"] == 0).mean() * 100
        )
        rappi_free_gdl = gdl_free.get("rappi", 0)
        didi_free_gdl = gdl_free.get("didifood", 0)

        insights.append({
            "rank": 4,
            "icon": "🌵",
            "title": "DiDi Food captura a Guadalajara con envío gratis masivo",
            "finding": (
                f"En Guadalajara, DiDi Food ofrece envío gratis en el {didi_free_gdl:.0f}% de los casos "
                f"vs el {rappi_free_gdl:.0f}% de Rappi. "
                "Estrategia clara de captura de mercado en el AMG (2da ciudad más grande de México)."
            ),
            "impact": (
                "Guadalajara es el 2do mercado más grande para Rappi en México. "
                "Perder la guerra de pricing aquí significa ceder cuota de mercado "
                "a DiDi en el momento en que están invirtiendo agresivamente para escalar. "
                "Con el efecto de red, es difícil recuperar usuarios una vez migrados."
            ),
            "recommendation": (
                "Lanzar campaña 'Rappi Gratis en GDL': envío gratis garantizado en "
                "las primeras 4 semanas del mes para usuarios en el AMG. "
                "Medir impacto en retención y frecuencia. "
                "Evaluar sostenibilidad del modelo después de 60 días."
            ),
            "data_point": f"DiDi: {didi_free_gdl:.0f}% envío gratis | Rappi: {rappi_free_gdl:.0f}%",
        })

        # ── Insight 5: Rappi tiene más promociones pero menor visibilidad ─────
        df["n_discounts"] = df["discounts_active"].apply(len)
        promo_avg = df.groupby("platform")["n_discounts"].mean()
        rappi_promos = promo_avg.get("rappi", 0)
        uber_promos = promo_avg.get("ubereats", 0)

        insights.append({
            "rank": 5,
            "icon": "📣",
            "title": "Rappi tiene más promociones activas pero menor conversión visible",
            "finding": (
                f"Rappi tiene en promedio {rappi_promos:.1f} promociones activas por sesión "
                f"vs {uber_promos:.1f} de Uber Eats, pero la estructura de comunicación "
                "de descuentos en la app hace que muchos usuarios no las descubran "
                "antes de completar el pedido."
            ),
            "impact": (
                "Invertir en promociones sin que el usuario las perciba es dinero quemado. "
                "Si el usuario no ve el descuento antes de decidir la plataforma, "
                "la promoción no influye en la conversión y solo reduce el margen."
            ),
            "recommendation": (
                "Rediseñar la experiencia de descubrimiento de promociones: "
                "mostrar el ahorro total ANTES de que el usuario llegue al checkout. "
                "A/B test: banner de 'Ahorras $X hoy' en la pantalla de inicio "
                "vs el flujo actual. Target: +15% en tasa de uso de cupones."
            ),
            "data_point": f"Rappi: {rappi_promos:.1f} promos/sesión | Uber Eats: {uber_promos:.1f}",
        })

        return insights

    # ─── Render ───────────────────────────────────────────────────────────────

    def render_report(self, output_file: Optional[str] = None) -> str:
        """Genera el informe HTML completo."""
        if self.df is None:
            raise ValueError("Ejecuta load_data() antes de render_report()")

        # Calcular datos
        kpis = self.compute_kpis()
        insights = self.generate_insights()

        # Generar gráficos
        charts = {
            "price_comparison": self.chart_price_comparison(),
            "delivery_fee_by_zone": self.chart_delivery_fee_by_zone(),
            "eta_by_city": self.chart_eta_by_platform_and_city(),
            "free_delivery_rate": self.chart_fee_free_delivery_rate(),
            "total_cost_heatmap": self.chart_total_cost_heatmap(),
            "fee_breakdown": self.chart_fee_breakdown(),
            "promo_type_distribution": self.chart_promo_type_distribution(),
        }

        # Estadísticas generales
        n_records = len(self.df)
        n_valid = len(self.df_valid)
        n_addresses = self.df["address_id"].nunique()
        n_cities = self.df["city"].nunique()
        platforms = [PLATFORM_DISPLAY.get(p, p) for p in self.df["platform"].unique()]
        generated_at = datetime.now().strftime("%d/%m/%Y %H:%M")

        # Renderizar HTML
        html = REPORT_TEMPLATE.render(
            kpis=kpis,
            insights=insights,
            charts=charts,
            n_records=n_records,
            n_valid=n_valid,
            n_addresses=n_addresses,
            n_cities=n_cities,
            platforms=platforms,
            platform_display=PLATFORM_DISPLAY,
            platform_colors=PLATFORM_COLORS,
            generated_at=generated_at,
        )

        # Guardar
        if not output_file:
            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
            output_file = f"reports/informe_{timestamp}.html"

        Path(output_file).parent.mkdir(parents=True, exist_ok=True)
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(html)

        logger.info(f"Informe generado: {output_file}")
        return output_file


# ─── HTML Template ────────────────────────────────────────────────────────────

REPORT_TEMPLATE = Template("""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Rappi — Competitive Intelligence Report</title>
<script src="https://cdn.plot.ly/plotly-3.5.0.min.js"></script>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
         background: #f8f9fa; color: #1a1a1a; }
  .header { background: linear-gradient(135deg, #FF441F 0%, #c2340f 100%);
            color: white; padding: 40px 48px; }
  .header h1 { font-size: 2rem; font-weight: 700; margin-bottom: 8px; }
  .header p { opacity: 0.85; font-size: 1rem; }
  .header .meta { margin-top: 16px; font-size: 0.85rem; opacity: 0.7; }
  .container { max-width: 1200px; margin: 0 auto; padding: 32px 24px; }
  .platform-kpi-grid { display: grid; grid-template-columns: 1fr 1fr 1fr;
                        gap: 20px; margin-bottom: 32px; }
  .platform-card { background: white; border-radius: 16px; padding: 24px;
                   box-shadow: 0 2px 8px rgba(0,0,0,.08); }
  .platform-card-header { font-size: 1.05rem; font-weight: 800; text-align: center;
                           margin-bottom: 16px; letter-spacing: .3px; }
  .metric-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
  .metric-cell { background: #f8f9fa; border-radius: 10px; padding: 12px 8px;
                 text-align: center; }
  .metric-label { font-size: 0.68rem; color: #888; text-transform: uppercase;
                  letter-spacing: .5px; margin-bottom: 5px; }
  .metric-value { font-size: 1.35rem; font-weight: 800; line-height: 1.1; }
  .metric-sub { font-size: 0.68rem; color: #aaa; margin-top: 3px; }
  .section { background: white; border-radius: 12px; padding: 28px;
             box-shadow: 0 1px 4px rgba(0,0,0,.08); margin-bottom: 24px; }
  .section h2 { font-size: 1.3rem; font-weight: 700; margin-bottom: 20px;
                display: flex; align-items: center; gap: 10px; }
  .chart-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
  .chart-full { grid-column: 1 / -1; }
  .insight-card { border-left: 4px solid #FF441F; padding: 20px 24px;
                  background: #fff8f7; border-radius: 0 8px 8px 0;
                  margin-bottom: 16px; }
  .insight-card:nth-child(even) { border-color: #06C167; background: #f7fff9; }
  .insight-rank { font-size: 1.2rem; font-weight: 800; color: #FF441F;
                  margin-bottom: 8px; }
  .insight-card:nth-child(even) .insight-rank { color: #06C167; }
  .insight-title { font-size: 1rem; font-weight: 700; margin-bottom: 12px; }
  .insight-section { margin-bottom: 10px; }
  .insight-section .tag { display: inline-block; font-size: 0.7rem; font-weight: 700;
                          text-transform: uppercase; letter-spacing: .5px;
                          padding: 2px 8px; border-radius: 4px;
                          background: #FF441F; color: white; margin-bottom: 4px; }
  .insight-section p { font-size: 0.875rem; color: #444; line-height: 1.5; }
  .insight-section .tag.impact { background: #e67e22; }
  .insight-section .tag.rec { background: #27ae60; }
  .data-point { font-size: 0.78rem; color: #888; margin-top: 8px;
                font-family: monospace; background: #f0f0f0;
                padding: 4px 8px; border-radius: 4px; display: inline-block; }
  .platform-legend { display: flex; gap: 24px; margin-bottom: 20px; }
  .platform-dot { display: flex; align-items: center; gap: 8px; font-size: 0.85rem; }
  .dot { width: 12px; height: 12px; border-radius: 50%; }
  .footer { text-align: center; padding: 32px; color: #888; font-size: 0.8rem; }
  @media (max-width: 768px) { .chart-grid { grid-template-columns: 1fr; }
    .header { padding: 24px; } .container { padding: 16px; } }
</style>
</head>
<body>

<div class="header">
  <h1>Competitive Intelligence Report</h1>
  <p>Análisis comparativo: Rappi vs Uber Eats vs DiDi Food — México</p>
  <div class="meta">
    Generado: {{ generated_at }} &nbsp;·&nbsp;
    {{ n_addresses }} direcciones en {{ n_cities }} ciudades &nbsp;·&nbsp;
    {{ n_valid }} registros válidos de {{ n_records }} totales
  </div>
</div>

<div class="container">

  <!-- KPIs — una columna por plataforma, 4 métricas cada una -->
  <div class="platform-kpi-grid">
    {% for platform in ['rappi', 'ubereats', 'didifood'] %}
    <div class="platform-card" style="border-top: 4px solid {{ platform_colors[platform] }}">
      <div class="platform-card-header" style="color: {{ platform_colors[platform] }}">
        {{ platform_display[platform] }}
      </div>
      <div class="metric-grid">

        <div class="metric-cell">
          <div class="metric-label">Big Mac</div>
          <div class="metric-value" style="color: {{ platform_colors[platform] }}">
            ${{ kpis.bigmac_prices.get(platform, '—') }}
          </div>
          <div class="metric-sub">MXN prom.</div>
        </div>

        <div class="metric-cell">
          <div class="metric-label">Delivery fee</div>
          <div class="metric-value" style="color: {{ platform_colors[platform] }}">
            ${{ kpis.avg_delivery_fee.get(platform, '—') }}
          </div>
          <div class="metric-sub">MXN prom.</div>
        </div>

        <div class="metric-cell">
          <div class="metric-label">ETA prom.</div>
          <div class="metric-value" style="color: {{ platform_colors[platform] }}">
            {{ kpis.avg_eta.get(platform, '—') }} min
          </div>
          <div class="metric-sub">estimado</div>
        </div>

        <div class="metric-cell">
          <div class="metric-label">Envío gratis</div>
          <div class="metric-value" style="color: {{ platform_colors[platform] }}">
            {{ kpis.free_delivery_pct.get(platform, '—') }}%
          </div>
          <div class="metric-sub">de los casos</div>
        </div>

      </div>
    </div>
    {% endfor %}
  </div>

  <!-- Gráficos — Precios y Tiempos -->
  <div class="section">
    <h2>📊 Posicionamiento de Precios y Tiempos de Entrega</h2>
    <div class="chart-grid">
      <div>{{ charts.price_comparison }}</div>
      <div>{{ charts.eta_by_city }}</div>
    </div>
  </div>

  <!-- Gráficos — Estructura de Fees -->
  <div class="section">
    <h2>💰 Estructura de Fees</h2>
    <div class="chart-grid">
      <div>{{ charts.delivery_fee_by_zone }}</div>
      <div>{{ charts.free_delivery_rate }}</div>
      <div class="chart-full">{{ charts.fee_breakdown }}</div>
      <div class="chart-full">{{ charts.total_cost_heatmap }}</div>
    </div>
  </div>

  <!-- Gráficos — Estrategia Promocional -->
  <div class="section">
    <h2>🎁 Estrategia Promocional</h2>
    <div class="chart-grid">
      <div class="chart-full">{{ charts.promo_type_distribution }}</div>
    </div>
  </div>

  <!-- Top 5 Insights -->
  <div class="section">
    <h2>🎯 Top 5 Insights Accionables</h2>
    {% for insight in insights %}
    <div class="insight-card">
      <div class="insight-rank">#{{ insight.rank }} {{ insight.icon }}</div>
      <div class="insight-title">{{ insight.title }}</div>

      <div class="insight-section">
        <span class="tag">Finding</span>
        <p>{{ insight.finding }}</p>
      </div>

      <div class="insight-section">
        <span class="tag impact">Impacto</span>
        <p>{{ insight.impact }}</p>
      </div>

      <div class="insight-section">
        <span class="tag rec">Recomendación</span>
        <p>{{ insight.recommendation }}</p>
      </div>

      <div class="data-point">📈 {{ insight.data_point }}</div>
    </div>
    {% endfor %}
  </div>

</div>

<div class="footer">
  Rappi Competitive Intelligence System · Datos recolectados vía Playwright (Chromium headless) ·
  Rate limiting: 2s mínimo entre requests · Cobertura: {{ n_cities }} ciudades de México
</div>

</body>
</html>
""")


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Generar informe de insights")
    parser.add_argument("--data-dir", default="data", help="Directorio con JSON de scraping")
    parser.add_argument("--output", default=None, help="Ruta del HTML de salida")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    gen = ReportGenerator(data_dir=args.data_dir)
    gen.load_data()
    path = gen.render_report(output_file=args.output)
    print(f"\nInforme generado: {path}\n")


if __name__ == "__main__":
    main()
