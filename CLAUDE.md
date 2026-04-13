# Rappi Competitive Intelligence — Web Scraper

Caso técnico para rol de AI Engineer en Rappi. Sistema automatizado de scraping competitivo que recolecta precios, fees y tiempos de entrega de Rappi, Uber Eats y DiDi Food en México, y genera insights accionables para los equipos de Pricing y Strategy.

## Stack

- **Lenguaje:** Python 3.11+
- **Scraping:** Playwright (navegador headless)
- **Análisis:** pandas, matplotlib / plotly
- **Output:** CSV / JSON + informe PDF o HTML
- **Automatización:** script único ejecutable por línea de comandos

## Comandos principales

```bash
# Instalar dependencias
pip install -r requirements.txt
playwright install chromium

# Ejecutar el scraper completo
python main.py

# Ejecutar solo un competidor
python main.py --platform ubereats
python main.py --platform didifood
python main.py --platform rappi

# Generar informe de insights
python reports/generate_report.py

# Ejecutar con direcciones específicas
python main.py --addresses addresses/cdmx_sample.json
```

## Estructura del proyecto

```
/
├── main.py                  # Entry point — orquesta el scraping
├── scrapers/
│   ├── base.py              # Clase base con retry logic y rate limiting
│   ├── ubereats.py
│   ├── didifood.py
│   └── rappi.py
├── config/
│   ├── addresses.json       # 20-50 direcciones representativas de México
│   └── products.json        # Productos de referencia (Big Mac, Coca-Cola, etc.)
├── data/                    # Output raw (CSV/JSON generados)
├── reports/
│   ├── generate_report.py   # Genera informe con visualizaciones
│   └── templates/
├── tests/
└── README.md
```

## Métricas que se recolectan

- Precio del producto (3-5 ítems de referencia por zona)
- Delivery fee (antes de descuentos)
- Service fee
- Tiempo estimado de entrega
- Descuentos / promociones activas
- Precio final total al usuario

## Productos de referencia

**Fast Food:** Big Mac, Combo mediano McDonald's, Nuggets 6 piezas  
**Retail:** Coca-Cola 500ml, Agua embotellada 1L

## Cobertura geográfica

20-50 direcciones en México cubriendo: CDMX (colonias populares, residenciales, periféricas), Guadalajara, Monterrey y zonas de expansión. Ver `config/addresses.json`.

## Convenciones de código

- Usar `logging` estándar de Python (no `print`)
- Toda función de scraping debe tener retry logic (máx 3 intentos)
- Rate limiting: mínimo 2s entre requests por dominio
- Respetar `robots.txt` cuando sea posible
- Variables de entorno para API keys y proxies (nunca hardcoded)
- Output siempre con timestamp en nombre de archivo: `data/ubereats_2025-10-12_14-30.csv`

## Variables de entorno requeridas

```bash
# Opcional — para proxies anti-detección
PROXY_URL=...
SCRAPER_API_KEY=...
```

Crear un `.env` local (nunca commitear). Ver `.env.example`.

## Consideraciones éticas

- Rate limiting razonable para no saturar servidores
- User-agents apropiados (navegador real simulado con Playwright)
- Documentar cualquier bloqueo encontrado y la solución aplicada
- Este scraping es de datos públicos para análisis competitivo

## Lo que NO hacer

- No hardcodear credenciales ni API keys
- No commitear la carpeta `data/` con datos scrapeados (está en `.gitignore`)
- No hacer scraping paralelo agresivo sin delays
- No ignorar errores silenciosamente — siempre loggear fallos
