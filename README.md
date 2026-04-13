# Rappi Competitive Intelligence System

Sistema automatizado de scraping competitivo para recolectar precios, delivery fees y tiempos de entrega de **Rappi**, **Uber Eats** y **DiDi Food** en México, con generación de insights accionables para los equipos de Pricing y Strategy.

---

## Quickstart

```bash
# 1. Instalar dependencias
pip install -r requirements.txt
playwright install chromium

# 2. Ejecutar con datos mock (recomendado para demo)
python main.py

# 3. Ver el informe generado
# Abrir reports/informe_YYYY-MM-DD_HH-MM.html en el navegador
```

---

## Comandos

```bash
# Demo completa: mock data + informe (sin riesgo de bloqueos)
python main.py

# Scraping real con Playwright (requiere IP mexicana para cobertura completa)
python main.py --live

# Solo una plataforma
python main.py --live --platform ubereats
python main.py --live --platform rappi didifood

# Ver el browser durante el scraping (debug)
python main.py --live --headful

# Limitar a 5 direcciones para test rápido
python main.py --live --limit-addresses 5

# Solo generar informe con datos existentes
python main.py --only-report

# Ejecutar tests
python -m pytest tests/ -v
```

---

## Arquitectura

```
/
├── main.py                    # Entry point con CLI (argparse)
├── scrapers/
│   ├── base.py                # Clase base: retry, rate limiting, stealth, screenshots
│   ├── ubereats.py            # Scraper Uber Eats México
│   ├── rappi.py               # Scraper Rappi México
│   ├── didifood.py            # Scraper DiDi Food México
│   └── mock_data.py           # Generador de datos realistas para demo/testing
├── config/
│   ├── addresses.json         # 30 direcciones representativas de México
│   └── products.json          # 5 productos de referencia (Big Mac, Coca-Cola, etc.)
├── data/                      # Output: JSON + CSV con timestamp
│   └── screenshots/           # Evidencia visual del scraping
├── reports/
│   └── generate_report.py     # Informe HTML interactivo con Plotly
└── tests/
    └── test_scrapers.py       # Tests de mock data, config y pipeline
```

---

## Métricas recolectadas

| Métrica | Fuente |
|---|---|
| Precio del producto | Menú del restaurante |
| Delivery fee | Header del restaurante |
| Service fee | Estimado (% sobre subtotal) |
| Tiempo de entrega (min/max) | Header del restaurante |
| Descuentos activos | Banners y etiquetas de la página |
| Disponibilidad del restaurante | Verificación de carga de menú |
| Precio final total | Suma de los anteriores |

---

## Cobertura geográfica

**30 direcciones** en 5 ciudades:

| Ciudad | Zonas cubiertas | # Direcciones |
|---|---|---|
| CDMX | Polanco, Condesa, Roma N., Tepito, Iztapalapa, Santa Fe, Coyoacán, Tlalpan, Ecatepec, Naucalpan, Xochimilco, Pedregal, Satélite, Cuautitlán | 15 |
| Guadalajara | Centro, Zapopan, Tlaquepaque, Providencia, Chapalita, Tonalá | 6 |
| Monterrey | Centro, San Pedro G.G., Sur, Santa Catarina, Apodaca, Escobedo | 6 |
| Puebla | Centro histórico | 1 |
| Cancún | Zona hotelera, Centro | 2 |

**Justificación de la selección:**
- **Tipos de zona**: high_income, mid_high, mid, popular, suburban, popular_suburban
- Cubre el espectro completo de sensibilidad al precio y densidad de repartidores
- Incluye zonas de expansión clave (Ecatepec, Apodaca, Escobedo) donde la competencia es más agresiva

---

## Productos de referencia

| Producto | Restaurante | Precio referencia |
|---|---|---|
| Big Mac | McDonald's | ~$95 MXN |
| Combo Mediano | McDonald's | ~$139 MXN |
| McNuggets 6 pzas | McDonald's | ~$85 MXN |
| Coca-Cola 500ml | OXXO | ~$22 MXN |
| Agua 1L | OXXO | ~$18 MXN |

**Justificación**: McDonald's está disponible en las 3 plataformas con menú idéntico, lo que permite comparación directa sin confounders de calidad o tamaño de porción.

---

## Setup

### Dependencias

```bash
pip install -r requirements.txt
playwright install chromium
```

### Variables de entorno (opcional)

```bash
cp .env.example .env
# Editar .env con tus credenciales de proxy si las tienes
```

| Variable | Descripción | Requerida |
|---|---|---|
| `PROXY_URL` | URL del proxy anti-detección | No |
| `SCRAPER_API_KEY` | API key de ScraperAPI | No |
| `HEADLESS` | `true`/`false` | No (default: true) |
| `MIN_DELAY` | Segundos entre requests | No (default: 2.0) |

---

## Limitaciones conocidas

1. **Geolocalización**: Para disponibilidad real por zona se requiere IP mexicana. Sin proxy, algunos restaurantes pueden no aparecer disponibles.

2. **Anti-bot**: Uber Eats usa Cloudflare y detección de headless. Rappi también tiene protecciones. En entorno sin proxy, se recomienda usar `--mock` para la demo.

3. **Selectores CSS**: Las SPAs React/Vue cambian su DOM con frecuencia. Los scrapers usan múltiples selectores como fallback, pero puede requerir actualización eventual.

4. **Service fee**: Solo visible en el checkout (requiere flujo de compra completo). Se estima como porcentaje del subtotal basado en valores públicos conocidos.

5. **DiDi Food**: Menor cobertura que Rappi/Uber Eats en zonas periféricas. Algunos restaurantes pueden no estar disponibles en todas las zonas.

---

## Consideraciones éticas

- Rate limiting mínimo de **2 segundos** entre requests por dominio (configurable)
- User-agents de navegadores reales (Chrome/Firefox actualizados)
- No se realizan peticiones paralelas agresivas
- Los datos scrapeados son **públicamente visibles** para cualquier usuario
- Se respetan los `robots.txt` en la medida en que no hay endpoints de API protegidos involucrados
- No se realiza login ni se acceden datos de usuarios privados

---

## Output

Cada ejecución genera en `data/`:
- `rappi_YYYY-MM-DD_HH-MM.json`
- `ubereats_YYYY-MM-DD_HH-MM.json`
- `didifood_YYYY-MM-DD_HH-MM.json`
- `combined_YYYY-MM-DD_HH-MM.json` (todos combinados)
- `combined_YYYY-MM-DD_HH-MM.csv` (para análisis en Excel/pandas)
- `scraping_YYYY-MM-DD.log` (log de la ejecución)
- `screenshots/` (evidencia visual, solo en modo live)

El informe se guarda en `reports/informe_YYYY-MM-DD_HH-MM.html`.
