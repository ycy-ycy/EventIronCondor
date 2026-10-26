import csv
import io
import math
import urllib.request

from .base import DataSourceError, RateSource


class FredRateSource(RateSource):
    key = "fred"
    label = "FRED DGS1"
    description = "St. Louis Fed DGS1 (1-year Treasury constant-maturity yield). Free, daily."

    URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS1"

    def get_us1y_yield_percent(self) -> float:
        """Fetch the latest available 1-year Treasury yield in percent.

        Do not fall back to Yahoo ^TNX, because ^TNX is a 10-year rate, not 1-year.
        If FRED is unavailable, fail loudly instead of silently using the wrong tenor.
        """
        try:
            with urllib.request.urlopen(self.URL, timeout=8) as response:
                text = response.read().decode("utf-8")

            latest = None
            reader = csv.DictReader(io.StringIO(text))
            for row in reader:
                raw = (row.get("DGS1") or "").strip()
                if not raw or raw == ".":
                    continue
                value = float(raw)
                if math.isfinite(value) and value > 0:
                    latest = value

            if latest is not None:
                return latest

        except Exception as exc:
            raise DataSourceError(f"Could not fetch US 1Y yield from FRED DGS1: {exc}")

        raise DataSourceError("Could not fetch US 1Y yield from FRED DGS1")
