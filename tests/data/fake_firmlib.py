import polars as pl


def load_daily(tickers: list[str]) -> pl.DataFrame:
    return pl.DataFrame({"ticker": tickers, "ret": [0.01] * len(tickers)})
