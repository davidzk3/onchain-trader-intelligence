from dataclasses import dataclass
import os
from dotenv import load_dotenv

load_dotenv()

@dataclass(frozen=True)
class Settings:
    solana_rpc: str
    wallet_a: str
    wallet_b: str

def get_settings() -> Settings:
    solana_rpc = os.getenv("SOLANA_RPC", "").strip()
    wallet_a = os.getenv("WALLET_A", "").strip()
    wallet_b = os.getenv("WALLET_B", "").strip()

    if not solana_rpc:
        raise ValueError("Missing SOLANA_RPC in .env")
    if not wallet_a or not wallet_b:
        raise ValueError("Missing WALLET_A or WALLET_B in .env")

    return Settings(
        solana_rpc=solana_rpc,
        wallet_a=wallet_a,
        wallet_b=wallet_b,
    )
