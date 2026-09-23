# -*- coding: utf-8 -*-
"""market_data.py - Series sincronizadas y distribucion, via IOL+YF (sin CSV).

API compatible con el modulo original:
  load_timeseries(ric, desde, hasta, fuentes) -> DataFrame[date, close, return]
  synchronise_timeseries(benchmark, security, ...) -> DataFrame
  synchronise_returns(rics, ...) -> DataFrame
  distribution(ric, ...) con compute_stats()
"""
import numpy as np
import pandas as pd
import scipy.stats as st
import matplotlib.pyplot as plt

import fuentes_datos as FD


def load_timeseries(ric, desde="2024-01-01", hasta=None, fuentes=None):
    df, src = FD.serie(ric, desde=desde, hasta=hasta, fuentes=fuentes)
    if df is None:
        raise RuntimeError(f"Sin serie para {ric}")
    t = pd.DataFrame()
    t["date"] = pd.to_datetime(df["date"], utc=True, errors="coerce").dt.normalize()
    t["close"] = df["close"].values
    t = t.sort_values(by="date", ascending=True)
    t["close_previous"] = t["close"].shift(1)
    t["return"] = t["close"] / t["close_previous"] - 1
    t = t.dropna(subset=["date", "close", "close_previous", "return"])
    t = t.reset_index(drop=True)
    t["source"] = src
    return t


def synchronise_timeseries(benchmark, security, desde="2024-01-01", hasta=None, fuentes=None):
    timeseries_x = load_timeseries(benchmark, desde=desde, hasta=hasta, fuentes=fuentes)
    timeseries_y = load_timeseries(security, desde=desde, hasta=hasta, fuentes=fuentes)
    if timeseries_x.empty or timeseries_y.empty:
        return pd.DataFrame()
    common_dates = pd.to_datetime(timeseries_x["date"]).isin(pd.to_datetime(timeseries_y["date"]))
    timeseries_x = timeseries_x[common_dates].sort_values(by="date").reset_index(drop=True)
    timeseries_y = timeseries_y[timeseries_y["date"].isin(timeseries_x["date"])].sort_values(by="date").reset_index(drop=True)
    timeseries = pd.DataFrame()
    timeseries["date"] = timeseries_x["date"]
    timeseries["close_x"] = timeseries_x["close"]
    timeseries["close_y"] = timeseries_y["close"]
    timeseries["return_x"] = timeseries_x["return"]
    timeseries["return_y"] = timeseries_y["return"]
    return timeseries


def synchronise_returns(rics, desde="2024-01-01", hasta=None, fuentes=None, workers=8):
    res = FD.batch_serie(rics, desde=desde, hasta=hasta, workers=workers)
    frames = {}
    for ric in rics:
        df, src = res.get(ric, (None, None))
        if df is None:
            raise RuntimeError(f"Sin serie para {ric}")
        t = pd.DataFrame({"date": pd.to_datetime(df["date"], utc=True, errors="coerce").dt.normalize(),
                          ric: pd.to_numeric(df["close"], errors="coerce").values})
        t = t.sort_values("date")
        t[ric + "_ret"] = t[ric] / t[ric].shift(1) - 1
        frames[ric] = t[["date", ric + "_ret"]].dropna()
    common_dates = set(frames[rics[0]]["date"])
    for ric in rics[1:]:
        common_dates = common_dates.intersection(set(frames[ric]["date"]))
    common_dates = sorted(common_dates)
    out = pd.DataFrame({"date": common_dates})
    for ric in rics:
        t = frames[ric]
        t = t[t["date"].isin(common_dates)].sort_values(by="date").reset_index(drop=True)
        out = out.merge(t[["date", ric + "_ret"]].rename(columns={ric + "_ret": ric}), on="date", how="left")
    return out


class distribution:
    def __init__(self, ric, desde="2024-01-01", hasta=None, fuentes=None, decimals=5):
        self.ric = ric
        self.desde, self.hasta, self.fuentes = desde, hasta, fuentes
        self.decimals = decimals
        self.str_title = None
        self.timeseries = None
        self.vector = None
        self.size = None
        self.mean_annual = None
        self.volatility_annual = None
        self.sharpe_ratio = None
        self.var_95 = None
        self.skewness = None
        self.kurtosis = None
        self.jb_stat = None
        self.p_value = None
        self.is_normal = None

    def load_timeseries(self):
        self.timeseries = load_timeseries(self.ric, desde=self.desde, hasta=self.hasta, fuentes=self.fuentes)
        self.vector = self.timeseries["return"].values
        self.size = len(self.vector)
        self.str_title = self.ric + " | datos IOL/YF"

    def plot_timeseries(self):
        plt.figure()
        self.timeseries.plot(kind="line", x="date", y="close", grid=True, color="blue",
                             title="Serie de precios de cierre para " + self.ric)
        plt.show()

    def compute_stats(self, factor=252):
        self.mean_annual = st.tmean(self.vector) * factor
        self.volatility_annual = st.tstd(self.vector) * np.sqrt(factor)
        self.sharpe_ratio = self.mean_annual / self.volatility_annual if self.volatility_annual > 0 else 0.0
        self.var_95 = np.percentile(self.vector, 5)
        self.skewness = st.skew(self.vector)
        self.kurtosis = st.kurtosis(self.vector)
        self.jb_stat = self.size / 6 * (self.skewness**2 + (self.kurtosis**2) / 4)
        self.p_value = 1 - st.chi2.cdf(self.jb_stat, df=2)
        self.is_normal = (self.p_value > 0.05)

    def plot_histogram(self):
        self.str_title += "\n" + "mean_annual=" + str(np.round(self.mean_annual, self.decimals)) \
            + " | " + "volatility_annual=" + str(np.round(self.volatility_annual, self.decimals)) \
            + "\n" + "sharpe_ratio=" + str(np.round(self.sharpe_ratio, self.decimals)) \
            + " | " + "var_95=" + str(np.round(self.var_95, self.decimals)) \
            + "\n" + "skewness=" + str(np.round(self.skewness, self.decimals)) \
            + " | " + "kurtosis=" + str(np.round(self.kurtosis, self.decimals)) \
            + "\n" + "JB stat=" + str(np.round(self.jb_stat, self.decimals)) \
            + " | " + "p-value=" + str(np.round(self.p_value, self.decimals)) \
            + "\n" + "is_normal=" + str(self.is_normal)
        plt.figure()
        plt.hist(self.vector, bins=100)
        plt.title(self.str_title)
        plt.show()
