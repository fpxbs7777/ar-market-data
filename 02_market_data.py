# -*- coding: utf-8 -*-
"""
02_market_data.py - Distribuciones con datos dual IOL+YF y mapeo automatico.

Uso:
    python 02_market_data.py AL30D
    python 02_market_data.py            # pide el simbolo por consola
    python 02_market_data.py MELID --desde 2024-01-01 --monto 10000

El simbolo se escribe tal cual (GGAL.BA, MELID, AAPL, AL30D, ^SPX) y el resto
(universo, formato Yahoo vs simbolo IOL sin .BA, fuente) se detecta solo con
MASTER_TICKERS_UNIFICADO.json via fuentes_datos.resolver().
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import scipy.stats as st

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fuentes_datos as FD


def load_timeseries(ric, desde="2024-01-01", hasta=None, fuentes=None):
    """Serie via IOL/YF con ruteo por universo (sin CSV)."""
    df, src = FD.serie(ric, desde=desde, hasta=hasta, fuentes=fuentes)
    if df is None:
        raise RuntimeError(f"Sin serie para {ric} en {fuentes or 'ruteo auto'}")
    t = pd.DataFrame()
    t["date"] = pd.to_datetime(df["date"], utc=True, errors="coerce")
    t["close"] = df["close"].values
    t["source"] = src
    t = t.sort_values(by="date").dropna().reset_index(drop=True)
    t["close_previous"] = t["close"].shift(1)
    t["return_close"] = t["close"] / t["close_previous"] - 1
    t = t.dropna().reset_index(drop=True)
    return t


class Distribution:
    def __init__(self, ric, investment_amount=10000, decimals=5, factor=252,
                 desde="2024-01-01", hasta=None, fuentes=None):
        self.ric = ric
        self.investment_amount = investment_amount
        self.decimals = decimals
        self.factor = factor
        self.desde, self.hasta, self.fuentes = desde, hasta, fuentes
        self.ficha = FD.resolver(ric)
        self.timeseries = None
        self.vector = None
        self.mean_annual = None
        self.volatility_annual = None
        self.sharpe_ratio = None
        self.var_95 = None
        self.skewness = None
        self.kurtosis = None
        self.jb_stat = None
        self.p_value = None
        self.is_normal = None
        self.max_loss = None
        self.expected_loss = None
        self.expected_gain = None
        self.max_gain = None
        self.most_probable = None
        self.current_price = None

    def describe_map(self):
        f = self.ficha
        print(f"Mapeo: {f['ticker']} -> universo={f['universo']} tipo={f['tipo']} "
              f"mercado={f['mercado']} moneda={f['moneda']}")
        print(f"  yahoo : {f['yf']}")
        print(f"  iol   : simbolo={f['iol']['simbolo']} mercado={f['iol']['mercado']} "
              f"instrumento={f['iol']['instrumento']} pais={f['iol']['pais']}")

    def load_timeseries(self):
        self.timeseries = load_timeseries(self.ric, desde=self.desde, hasta=self.hasta,
                                          fuentes=self.fuentes)
        self.vector = self.timeseries["return_close"].values
        self.current_price = self.timeseries["close"].iloc[-1]
        self.source = self.timeseries["source"].iloc[0]

    def compute_stats(self):
        self.mean_annual = np.mean(self.vector) * self.factor
        self.volatility_annual = np.std(self.vector) * np.sqrt(self.factor)
        self.sharpe_ratio = self.mean_annual / self.volatility_annual if self.volatility_annual > 0 else 0.0
        self.var_95 = np.percentile(self.vector, 5)
        self.skewness = st.skew(self.vector)
        self.kurtosis = st.kurtosis(self.vector)
        self.jb_stat = len(self.vector) / 6 * (self.skewness**2 + (1 / 4) * self.kurtosis**2)
        self.p_value = 1 - st.chi2.cdf(self.jb_stat, df=2)
        self.is_normal = self.p_value > 0.05
        self.max_loss = self.current_price * self.var_95
        self.expected_loss = self.current_price * np.mean(self.vector[self.vector < 0])
        self.expected_gain = self.current_price * np.mean(self.vector[self.vector > 0])
        self.max_gain = self.current_price * np.max(self.vector)
        self.most_probable = self.current_price * np.median(self.vector)

        print(f"Datos para {self.ric} (fuente={self.source}):")
        print(f"  Precio Actual: {self.current_price:.2f}")
        print(f"  Media Anualizada: {self.mean_annual:.5f}")
        print(f"  Volatilidad Anualizada: {self.volatility_annual:.5f}")
        print(f"  Ratio de Sharpe: {self.sharpe_ratio:.5f}")
        print(f"  JB Stat: {self.jb_stat:.5f}, p-value: {self.p_value:.5f}")
        print(f"  ¿Distribución Normal?: {self.is_normal}")

    def plot_histogram(self):
        title = (
            f"{self.ric} | mean_annual={self.mean_annual:.{self.decimals}f} "
            f"| volatility_annual={self.volatility_annual:.{self.decimals}f}\n"
            f"sharpe_ratio={self.sharpe_ratio:.{self.decimals}f} | var_95={self.var_95:.{self.decimals}f}\n"
            f"skewness={self.skewness:.{self.decimals}f} | kurtosis={self.kurtosis:.{self.decimals}f}\n"
            f"JB_stat={self.jb_stat:.{self.decimals}f} | p-value={self.p_value:.{self.decimals}f}\n"
            f"is_normal={self.is_normal}"
        )
        plt.figure()
        plt.hist(self.vector, bins=100, alpha=0.75, edgecolor="black")
        plt.title(title)
        plt.xlabel("Returns")
        plt.ylabel("Frequency")
        plt.show()

    def plot_timeseries(self):
        plt.figure()
        plt.plot(self.timeseries["date"], self.timeseries["close"], color="blue", label="Close Price")
        plt.title(f"Timeseries of close prices for {self.ric}")
        plt.xlabel("Date")
        plt.ylabel("Price")
        plt.grid(True)
        plt.legend()
        plt.show()

    def diagnose_investment(self):
        if self.mean_annual > 0 and self.sharpe_ratio > 1 and self.volatility_annual < 0.2 and self.var_95 > -0.2:
            return "Los resultados indican que es favorable invertir en el activo."
        return "Los resultados indican que no es favorable invertir en el activo."


def pedir_ticker(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="02_market_data: distribucion con IOL+YF y mapeo auto.")
    ap.add_argument("ticker", nargs="?", help="ej GGAL.BA, MELID, AAPL, AL30D, ^SPX")
    ap.add_argument("--desde", default="2024-01-01")
    ap.add_argument("--hasta", default=None)
    ap.add_argument("--monto", type=float, default=10000)
    ap.add_argument("--fuentes", nargs="*", default=None)
    ap.add_argument("--sin-graficos", action="store_true")
    args = ap.parse_args(argv)
    t = args.ticker or input("simbolo (ej GGAL.BA, MELID, AAPL, AL30D, ^SPX): ").strip()
    t = t.strip().upper()
    if not t:
        ap.error("falta simbolo")
    return args, t


if __name__ == "__main__":
    args, ric = pedir_ticker()
    dist = Distribution(ric, investment_amount=args.monto, desde=args.desde,
                        hasta=args.hasta, fuentes=args.fuentes)
    dist.describe_map()
    dist.load_timeseries()
    print(f"Serie: {len(dist.timeseries)} ruedas, fuente={dist.source}")
    if not args.sin_graficos:
        dist.plot_timeseries()
    dist.compute_stats()
    if not args.sin_graficos:
        dist.plot_histogram()
    print("Diagnóstico:", dist.diagnose_investment())
