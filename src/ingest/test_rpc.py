import httpx
from configs.settings import get_settings

def main():
    s = get_settings()
    payload = {"jsonrpc":"2.0","id":1,"method":"getHealth"}
    r = httpx.post(s.solana_rpc, json=payload, timeout=30)
    print("HTTP", r.status_code)
    print(r.text[:500])

if __name__ == "__main__":
    main()
