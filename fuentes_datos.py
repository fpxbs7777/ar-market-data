# -*- coding: utf-8 -*-
"""
fuentes_datos.py - Capa dual IOL + yfinance con ruteo por universo.
Version paquete ar-market-data (autocontenida).

Universos (MASTER_TICKERS_UNIFICADO.json -> lookup[].universo):
  ACCIONES_AR  : IOL primario (BCBA, simbolo sin .BA) | YF fallback (GGAL.BA)
  CEDEAR       : IOL primario (ARS: base, D/C: base+D/C) | YF fallback (.BA / subyacente US)
  ACCIONES_US  : YF primario | IOL secundario (acciones/estados_Unidos)
  ETF          : YF primario (US) | IOL secundario (BCBA p/ GD30D.BA y CEDEAR-ETF)
  RENTA_FIJA   : IOL unico (bonos/ON/letras/cauciones no estan en Yahoo)
  FUTURO/OPCION: IOL unico (Rofex/BCBA); YF option_chain solo p/ subyacente US
  FACTOR       : YF unico (^SPX, EURUSD=X, BTC-USD, DX-Y.NYB)
  ANEXO        : YF (accion US)
"""
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests

_HERE = Path(__file__).resolve().parent
_MASTER_CANDS = [
    _HERE / "MASTER_TICKERS_UNIFICADO.json",
    Path(r"C:\Users\boosa\Downloads\PROTOTIPO-CON-DATOS-EN-TIEMPO-REAL-main\MASTER_TICKERS_UNIFICADO.json"),
]
_ENV_CANDS = [_HERE / ".env"]

IOL_TOKEN_URL = "https://api.invertironline.com/token"
IOL_BASE = "https://api.invertironline.com/api/v2"

_MASTER = None
_LOOKUP = {}
_ALIASES = {}
_TOK = {"access": None, "exp": 0}


def _load_master():
    global _MASTER, _LOOKUP, _ALIASES
    if _MASTER is not None:
        return _MASTER
    for p in _MASTER_CANDS:
        if p.is_file():
            _MASTER = json.loads(p.read_text(encoding="utf-8"))
            break
    if _MASTER is None:
        raise FileNotFoundError("No se encontro MASTER_TICKERS_UNIFICADO.json junto al script")
    _LOOKUP = _MASTER.get("lookup") or _MASTER.get("tickers") or {}
    _ALIASES = _MASTER.get("aliases", {})
    return _MASTER


def _load_env():
    for p in _ENV_CANDS:
        if p.is_file():
            for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())
            return


def iol_token():
    if _TOK["access"] and time.time() < _TOK["exp"] - 60:
        return _TOK["access"]
    _load_env()
    user, pwd = os.environ.get("IOL_USERNAME", ""), os.environ.get("IOL_PASSWORD", "")
    if not user or not pwd:
        raise RuntimeError("IOL_USERNAME/IOL_PASSWORD no configurados: copia .env.example a .env")
    r = requests.post(IOL_TOKEN_URL, data={"username": user, "password": pwd, "grant_type": "password"},
                      headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=15)
    r.raise_for_status()
    _TOK.update({"access": r.json().get("access_token"), "exp": time.time() + 1500})
    return _TOK["access"]


def iol_get(url, params=None, timeout=20):
    try:
        r = requests.get(url, headers={"Accept": "application/json", "Authorization": f"Bearer {iol_token()}"},
                         params=params, timeout=timeout)
        return r.json() if r.status_code == 200 else None
    except Exception:
        return None


def resolver(ticker):
    """Ficha unica: {ticker, universo, tipo, mercado, moneda, yf, iol:{simbolo,mercado,instrumento,pais}}."""
    _load_master()
    import re as _re
    t = str(ticker).strip().upper().replace(" ", "")
    mrx = _re.match(r"^([A-Z0-9.]+)/([A-Z]{3}\d{2,4})$", t)
    if mrx:  # futuro Rofex: DLR/SEP26, GGAL/OCT26, RFX20/DIC26 (IOL unico, sin Yahoo)
        sub = mrx.group(1)
        usd_fam = ("ORO", "WTI", "BTC", "SOJ", "SOY", "MAI", "TRI", "CRN", "CNH")
        return {"ticker": t, "universo": "FUTURO", "tipo": "futuro", "mercado": "ROFEX",
                "moneda": ("USD" if sub in usd_fam else "ARS"), "nombre": "Futuro Rofex " + t,
                "yf": None,
                "iol": {"simbolo": t, "mercado": "Rofex", "instrumento": "futuros", "pais": "argentina"}}
    if t in _ALIASES and t not in _LOOKUP:
        t = _ALIASES[t]
    e = _LOOKUP.get(t)
    if e is None:
        e = {"ticker": t, "tipo": "accion", "mercado": "BCBA" if t.endswith(".BA") else "NYSE/NASDAQ",
             "moneda": "ARS" if t.endswith(".BA") else "USD", "universo": "DESCONOCIDO", "nombre": t}
    uni = e.get("universo") or ("ACCIONES_AR" if e.get("mercado") == "BCBA" and e.get("tipo") == "accion"
                                else ("CEDEAR" if e.get("tipo") == "cedear" else "ACCIONES_US"))
    base = t[:-3] if t.endswith(".BA") else t  # IOL: sin .BA (GGAL.BA->GGAL, MELI.BA->MELI, MELID->MELID)
    mercado_iol = "Rofex" if uni == "FUTURO" else "bCBA"
    instrumento = {"ACCIONES_AR": "acciones", "CEDEAR": "cedears", "ACCIONES_US": "acciones",
                   "ETF": "cedears" if t.endswith(".BA") else "acciones",
                   "RENTA_FIJA": ("titulosPublicos" if e.get("tipo") == "titulo_publico"
                                  else "obligacionesNegociables"),
                   "FUTURO": "futuros", "OPCION": "opciones"}.get(uni)
    try:
        _adr_us = {a.get("ticker") for a in (_MASTER.get("adrs") or {}).get("argentina", [])}
    except Exception:
        _adr_us = set()
    instrumento = instrumento if uni != "ANEXO_SIN_CLASIFICAR" else ("adrs" if t in _adr_us else None)
    pais_iol = ("argentina" if (e.get("mercado") == "BCBA"
                                or uni in ("ACCIONES_AR", "CEDEAR", "RENTA_FIJA", "FUTURO", "OPCION")
                                or t in _adr_us)
                else "estados_Unidos")
    return {"ticker": t, "universo": uni, "tipo": e.get("tipo"), "mercado": e.get("mercado"),
            "moneda": e.get("moneda"), "nombre": e.get("nombre", t),
            "yf": e.get("ticker_yahoo", t),
            "iol": {"simbolo": base, "mercado": mercado_iol, "instrumento": instrumento, "pais": pais_iol}}


RUTEO = {
    "ACCIONES_AR": [("IOL", "spot BCBA"), ("YF", "fallback .BA")],
    "CEDEAR": [("IOL", "ARS base / D-C MEP"), ("YF", "fallback .BA/subyacente")],
    "ACCIONES_US": [("YF", "mercado origen"), ("IOL", "panel eeuu")],
    "ETF": [("YF", "mercado origen"), ("IOL", "cedear ETF BCBA")],
    "RENTA_FIJA": [("IOL", "solo IOL")],
    "FUTURO": [("IOL", "solo Rofex")],
    "OPCION": [("IOL", "BCBA Opciones"), ("YF", "option_chain US")],
    "FACTOR": [("YF", "indices/FX/crypto")],
    "ANEXO_SIN_CLASIFICAR": [("YF", "accion US")],
    "DESCONOCIDO": [("IOL", "intento BCBA"), ("YF", "intento Yahoo")],
}


def _norm_serie(df, source):
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce", format="mixed")
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df = df.dropna(subset=["date", "close"]).sort_values("date").reset_index(drop=True)
    df["source"] = source
    return df[["date", "close", "source"]]


def serie_iol(ticker, desde="2024-01-01", hasta=None, ajustada="ajustada", diaria=True):
    """GET /{mercado}/Titulos/{simbolo}/Cotizacion/seriehistorica/{desde}/{hasta}/{ajustada}.

    IOL devuelve /ajustada vacia para bonos y varios cedears -> fallback a /sinAjustar.
    diaria=True agrupa por dia calendario (ultimo) porque sinAjustar trae varias filas por dia."""
    f = resolver(ticker)
    if f["iol"]["instrumento"] is None:
        return None
    hasta = hasta or datetime.now().strftime("%Y-%m-%d")
    from urllib.parse import quote as _q
    sim = _q(f["iol"]["simbolo"], safe="")
    for aj in ([ajustada] if ajustada != "ajustada" else ["ajustada", "sinAjustar"]):
        url = (f"{IOL_BASE}/{f['iol']['mercado']}/Titulos/{sim}"
               f"/Cotizacion/seriehistorica/{desde}/{hasta}/{aj}")
        try:
            j = iol_get(url, timeout=25)
            if not isinstance(j, list) or not j:
                continue
            df = pd.DataFrame(j)
            col_f = "fechaHora" if "fechaHora" in df.columns else "fecha"
            out = _norm_serie(pd.DataFrame({"date": df[col_f], "close": df.get("ultimoPrecio", df.get("close"))}),
                              "IOL" + ("" if aj == "ajustada" else "-sinAjustar"))
            if diaria and len(out):
                out["day"] = out["date"].dt.date
                out = out.groupby("day", as_index=False).last().drop(columns="day").sort_values("date")
                out = out.reset_index(drop=True)
            if len(out) >= 2:
                return out
        except Exception:
            continue
    return None


def serie_yf(ticker, desde="2024-01-01", hasta=None):
    """yf.download sobre ticker_yahoo del master (GGAL.BA, AAPL, ^SPX, EURUSD=X, BTC-USD)."""
    f = resolver(ticker)
    if not f.get("yf"):
        return None
    try:
        import yfinance as yf
    except ImportError:
        return None
    try:
        df = yf.download(f["yf"], start=desde, end=hasta, auto_adjust=True, progress=False, threads=False)
        if df is None or df.empty:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            close = df["Close"].iloc[:, 0] if "Close" in df.columns.get_level_values(0) else df.iloc[:, 0]
        else:
            close = df["Close"] if "Close" in df.columns else df.iloc[:, 0]
        out = _norm_serie(pd.DataFrame({"date": pd.to_datetime(close.index), "close": close.values}), "YF")
        return out if len(out) >= 2 else None
    except Exception:
        return None


def serie(ticker, desde="2024-01-01", hasta=None, fuentes=None):
    """Serie con failover segun RUTEO. Retorna (df, fuente_usada)."""
    f = resolver(ticker)
    orden = fuentes or [s for s, _ in RUTEO.get(f["universo"], RUTEO["DESCONOCIDO"])]
    for src in orden:
        df = serie_iol(ticker, desde, hasta) if src == "IOL" else serie_yf(ticker, desde, hasta)
        if df is not None:
            return df, src
    return None, None


def batch_serie(tickers, desde="2024-01-01", hasta=None, workers=8):
    """Series en paralelo respetando ruteo por ticker. Retorna {ticker: (df, fuente)}."""
    out = {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(serie, t, desde, hasta): t for t in tickers}
        for fut in as_completed(futs):
            t = futs[fut]
            try:
                out[t] = fut.result()
            except Exception as e:
                out[t] = (None, "ERR:%s" % e)
    return out


def cotizacion(ticker):
    """Detalle IOL (puntas, OHLC, monto) con fallback a fast_info YF.

    GET /{mercado}/Titulos/{simbolo}/CotizacionDetalle."""
    f = resolver(ticker)
    if "IOL" in [s for s, _ in RUTEO.get(f["universo"], [])]:
        j = iol_get(f"{IOL_BASE}/{f['iol']['mercado']}/Titulos/{f['iol']['simbolo']}/CotizacionDetalle")
        if j:
            j["source"] = "IOL"
            return j
    try:
        import yfinance as yf
        fi = yf.Ticker(f["yf"]).fast_info
        return {"simbolo": ticker, "ultimoPrecio": float(fi.get("last_price")),
                "moneda": fi.get("currency"), "source": "YF"}
    except Exception:
        return None


_VOL_COLS = ["montoOperado", "volumenNominal", "volumen", "volumenOperado", "cantidadOperada"]


def panel(instrumento, pais="argentina", top=None):
    """Panel IOL: GET /Cotizaciones/{instrumento}/{pais}/Todos, ordenado por volumen desc."""
    j = iol_get(f"{IOL_BASE}/Cotizaciones/{instrumento}/{pais}/Todos",
                params={"cotizacionInstrumentoModel.instrumento": instrumento,
                        "cotizacionInstrumentoModel.pais": pais})
    titulos = (j or {}).get("titulos", []) if isinstance(j, dict) else []
    df = pd.DataFrame(titulos)
    if df.empty:
        return df
    col = next((c for c in _VOL_COLS if c in df.columns), None)
    if col is not None:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
        df = df.sort_values(col, ascending=False).reset_index(drop=True)
    df["source"] = "IOL"
    return df.head(top) if top else df


def _especie_cedear(simbolo):
    """ARS/D/C via listas del master + heuristica de sufijo."""
    _load_master()
    s = str(simbolo).upper().strip()
    listas = (_MASTER.get("cedears") or {}).get("listas_planas", {})
    if s in listas.get("ars", []) or s + ".BA" in listas.get("ars", []):
        return "ARS"
    if s in listas.get("usd", []):
        return "D"
    sn = s.replace(".BA", "")
    if sn in {x.replace(".BA", "") for x in listas.get("ars", [])}:
        return "ARS"
    if s.endswith("D") and len(s) > 1:
        return "D"
    if s.endswith("C") and len(s) > 1:
        return "C"
    return "ARS"


def panel_cedears(especie="ARS", top=None):
    """CEDEARs IOL spliteados por especie ARS/D/C."""
    df = panel("cedears", "argentina")
    if df.empty or "simbolo" not in df.columns:
        return df
    df = df.copy()
    df["especie"] = df["simbolo"].apply(_especie_cedear)
    out = df[df["especie"] == especie.upper()].reset_index(drop=True)
    return out.head(top) if top else out


def opciones(subyacente, mercado="bCBA"):
    """Opciones BCBA: GET /{mercado}/Titulos/{simbolo}/Opciones. YF option_chain si subyacente US."""
    j = iol_get(f"{IOL_BASE}/{mercado}/Titulos/{str(subyacente).replace('.BA', '')}/Opciones")
    if j:
        return {"source": "IOL", "opciones": j}
    try:
        import yfinance as yf
        t = yf.Ticker(resolver(subyacente)["yf"])
        if t.options:
            ch = t.option_chain(t.options[0])
            return {"source": "YF", "vencimiento": t.options[0], "calls": ch.calls, "puts": ch.puts}
    except Exception:
        pass
    return None


def fci(simbolo=None):
    """FCI IOL (solo IOL): /Titulos/FCI[/{simbolo}]."""
    return iol_get(f"{IOL_BASE}/Titulos/FCI" + ("/%s" % simbolo if simbolo else ""))


def mep(simbolo):
    """Dolar MEP IOL: GET /Cotizaciones/MEP/{simbolo} (solo IOL)."""
    return iol_get(f"{IOL_BASE}/Cotizaciones/MEP/{simbolo}")


def ficha_stats(ticker, desde="2024-01-01", hasta=None, fuentes=None):
    """Resuelve, mapea, descarga y calcula stats estilo 02_market_data. Retorna dict."""
    import numpy as np
    import scipy.stats as st
    f = resolver(ticker)
    df, src = serie(ticker, desde, hasta, fuentes)
    out = {"ficha": f, "fuente": src, "filas": 0 if df is None else len(df)}
    if df is None:
        out["error"] = "sin serie en %s" % (fuentes or [s for s, _ in RUTEO[f["universo"]]])
        return out
    ret = df["close"].values[1:] / df["close"].values[:-1] - 1
    ret = ret[~np.isnan(ret)]
    curr = float(df["close"].iloc[-1])
    mean_ann = float(np.mean(ret) * 252)
    vol_ann = float(np.std(ret, ddof=1) * np.sqrt(252)) if len(ret) > 1 else 0.0
    var95 = float(np.percentile(ret, 5))
    skew = float(st.skew(ret))
    kurt = float(st.kurtosis(ret))
    jb = float(len(ret) / 6 * (skew ** 2 + (kurt ** 2) / 4))
    pval = float(1 - st.chi2.cdf(jb, df=2))
    out.update({"desde": str(df["date"].iloc[0]), "hasta": str(df["date"].iloc[-1]), "n": len(ret),
                "close": curr, "mean_annual": mean_ann, "volatility_annual": vol_ann,
                "sharpe_ratio": mean_ann / vol_ann if vol_ann > 0 else 0.0, "var_95": var95,
                "skewness": skew, "kurtosis": kurt, "jb_stat": jb, "p_value": pval,
                "is_normal": pval > 0.05,
                "max_gain": float(curr * ret.max()), "expected_gain": float(curr * ret[ret > 0].mean()),
                "expected_loss": float(curr * ret[ret < 0].mean()), "max_loss": float(curr * var95)})
    return out


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="Datos dual IOL+YF con ruteo por universo (MASTER_TICKERS_UNIFICADO).")
    ap.add_argument("ticker", nargs="?", help="ej GGAL.BA, MELID, AAPL, AL30D, ^SPX, DLR/SEP26")
    ap.add_argument("--desde", default="2024-01-01")
    ap.add_argument("--hasta", default=None)
    ap.add_argument("--fuentes", nargs="*", default=None, help="ej --fuentes IOL YF (fuerza orden)")
    ap.add_argument("--no-stats", action="store_true")
    ap.add_argument("--cotizacion", action="store_true", help="muestra detalle/cotizacion en vez de serie")
    args = ap.parse_args(argv)
    t = args.ticker
    if not t:
        try:
            t = input("ticker (ej GGAL.BA, MELID, AAPL, AL30D, ^SPX): ").strip()
        except EOFError:
            t = ""
    if not t:
        ap.error("falta ticker")
    f = resolver(t)
    print("mapeo: %s -> universo=%s tipo=%s mercado=%s moneda=%s" % (
        f["ticker"], f["universo"], f["tipo"], f["mercado"], f["moneda"]))
    print("  yahoo : %s" % f["yf"])
    print("  iol   : simbolo=%s mercado=%s instrumento=%s pais=%s" % (
        f["iol"]["simbolo"], f["iol"]["mercado"], f["iol"]["instrumento"], f["iol"]["pais"]))
    print("  ruteo : %s" % [s for s, _ in RUTEO[f["universo"]]])
    if args.cotizacion:
        print("cotizacion:", cotizacion(t))
        return
    r = ficha_stats(t, args.desde, args.hasta, args.fuentes)
    if "error" in r:
        print("ERROR:", r["error"])
        return
    print("fuente: %s | filas: %d | %s -> %s | n=%d" % (r["fuente"], r["filas"], r["desde"], r["hasta"], r["n"]))
    if not args.no_stats:
        print("close: %.2f | media anual: %.5f | vol anual: %.5f | sharpe: %.5f" % (
            r["close"], r["mean_annual"], r["volatility_annual"], r["sharpe_ratio"]))
        print("VaR95: %.5f | skew: %.5f | kurt: %.5f | JB: %.2f p=%.4g normal=%s" % (
            r["var_95"], r["skewness"], r["kurtosis"], r["jb_stat"], r["p_value"], r["is_normal"]))


if __name__ == "__main__":
    main()
