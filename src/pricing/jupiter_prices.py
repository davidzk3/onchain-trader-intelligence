import time
import httpx
from typing import Optional
from rich.console import Console

console = Console()

# Stablecoin mint constants (Solana mainnet)
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
USDT_MINT = "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"

# Jupiter price endpoint (v6 recommended)
JUPITER_PRICE_URL = "https://price.jup.ag/v6/price"


class JupiterPriceClient:
    def __init__(self, timeout: float = 10.0, max_retries: int = 3):
        self.timeout = timeout
        self.max_retries = max_retries

    def get_price(self, mint: str) -> Optional[float]:
        """
        Fetch spot USD price for a Solana mint using Jupiter.
        Uses fallback for common stablecoins (USDC/USDT).
        """
        mint = (mint or "").strip()
        if not mint:
            return None

        # Return immediate known prices for stables
        if mint == USDC_MINT:
            return 1.0
        if mint == USDT_MINT:
            return 1.0

        params = {"ids": mint}

        last_err: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                with httpx.Client(timeout=self.timeout) as client:
                    resp = client.get(JUPITER_PRICE_URL, params=params)
                    resp.raise_for_status()
                    data = resp.json()

                # Expected shape:
                # { "data": { "<mint>": { "price": <float> } } }
                price_obj = data.get("data", {}).get(mint)
                if not price_obj:
                    return None

                price = price_obj.get("price")
                if price is None:
                    return None

                return float(price)

            except Exception as e:
                last_err = e
                console.print(f"[yellow]Jupiter price attempt {attempt}/{self.max_retries} failed[/yellow]: {e}")
                time.sleep(0.5 * attempt)

        console.print(f"[red]Price fetch failed after retries for mint {mint}[/red]: {last_err}")
        return None
