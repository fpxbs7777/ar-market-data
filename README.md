# ar-market-data

Capa dual de datos de mercado para Argentina: **IOL (InvertirOnline) + Yahoo Finance**, con mapeo automático de tickers por universo (acciones BCBA, CEDEARs ARS/D/C, ADRs, bonos, ETFs, índices, ROFEX).

Problema que resuelve: cada fuente usa un formato distinto (`GGAL.BA` en Yahoo vs `GGAL` en IOL, `MELID` MEP, `^SPX`, `DLR/SEP26`). Este paquete escribe el símbolo una sola vez y detecta el resto desde `MASTER_TICKERS_UNIFICADO.json` (5.600+ tickers, 8 universos).

## Funciones

- Ruteo por universo: IOL primero para BCBA/bonos/Rofex, Yahoo primero para US/índices/FX/crypto, con failover automático.
- Series diarias (`serie`, `batch_serie`), cotización con puntas (`cotizacion`), paneles IOL por volumen, split CEDEAR ARS/D/C, opciones BCBA + `option_chain` Yahoo, FCI y dólar MEP.
- `02_market_data.py`: análisis de distribución (media/vol anual, Sharpe, VaR95, Jarque-Bera) con prompt de símbolo en consola.
- `market_data.py`: series sincronizadas y retornos multi-ticker para CAPM/portfolios.

## Tecnologías

Python · yfinance · IOL API v2 · pandas · numpy · scipy · matplotlib · requests

## Instalación

```bash
pip install -r requirements.txt
cp .env.example .env   # completar con credenciales IOL (solo necesarias para BCBA/bonos/Rofex)
```

## Uso

```bash
python 02_market_data.py AL30D --desde 2024-01-01
python 02_market_data.py MELID
python fuentes_datos.py GGAL.BA --cotizacion
```

```python
from fuentes_datos import serie, batch_serie, cotizacion
df, fuente = serie("GGAL.BA", desde="2025-01-01")   # IOL
df, fuente = serie("AAPL", desde="2025-01-01")      # Yahoo
```

## Estructura

| Archivo | Rol |
|---|---|
| `fuentes_datos.py` | Capa dual IOL+YF (`resolver`, `serie`, `panel`, `opciones`, `fci`, `mep`) |
| `02_market_data.py` | CLI + clase `Distribution` (stats y gráficos) |
| `market_data.py` | Series sincronizadas multi-ticker |
| `MASTER_TICKERS_UNIFICADO.json` | Mapa ticker → universo/tipo/mercado/moneda/Yahoo/IOL |

## Nota

Se requiere cuenta IOL solo para datos BCBA/bonos/Rofex. Yahoo cubre acciones US, ADRs, ETFs, índices, FX y crypto sin credenciales. No es asesoramiento financiero.

## Servicios

Puedo ayudarte con: instalación y configuración, paneles a medida (Top N por volumen), backtests CAPM/portfolios, opciones y futuros ROFEX, y mantenimiento.

Contacto: [tu-email@ejemplo.com](mailto:tu-email@ejemplo.com)
