import os
import numpy as np
import pandas as pd

# Force safe non-interactive backend (important on Windows sometimes)
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from sklearn.preprocessing import StandardScaler
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from rich.console import Console

console = Console()


def main():
    os.makedirs("artifacts", exist_ok=True)

    df = pd.read_csv("artifacts/trader_features.csv")
    if df.empty:
        raise ValueError("artifacts/trader_features.csv is empty. Run: python -m src.features.trader_features")

    X = df.drop(columns=["wallet_label"])
    labels = df["wallet_label"].astype(str)

    # Ensure numeric
    X = X.apply(pd.to_numeric, errors="coerce").fillna(0.0)

    # Scale features
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    # KMeans (k=2 for now)
    kmeans = KMeans(n_clusters=2, random_state=42, n_init=10)
    clusters = kmeans.fit_predict(X_scaled)
    df["cluster"] = clusters

    # PCA for visualization
    pca = PCA(n_components=2, random_state=42)
    coords = pca.fit_transform(X_scaled)

    # Sanitize coords to prevent bbox overflow
    coords = np.nan_to_num(coords, nan=0.0, posinf=0.0, neginf=0.0)

    df["x"] = coords[:, 0]
    df["y"] = coords[:, 1]

    # Plot
    plt.figure(figsize=(6, 5), dpi=120)
    for _, row in df.iterrows():
        plt.scatter(row["x"], row["y"], s=120)
        plt.text(float(row["x"]) + 0.02, float(row["y"]) + 0.02, str(row["wallet_label"]), fontsize=12)

    plt.title("Trader Behavior Clusters")
    plt.xlabel("PC1")
    plt.ylabel("PC2")
    plt.grid(True)
    plt.tight_layout()

    out_img = "artifacts/trader_clusters.png"
    plt.savefig(out_img)  # <-- NO bbox_inches="tight"
    plt.close()

    df_out = "artifacts/trader_clusters.csv"
    df.to_csv(df_out, index=False)

    console.print("[green]Saved[/green] artifacts/trader_clusters.csv")
    console.print("[green]Saved[/green] artifacts/trader_clusters.png")
    console.print(df[["wallet_label", "cluster"]])


if __name__ == "__main__":
    main()
