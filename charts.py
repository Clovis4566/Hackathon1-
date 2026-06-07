"""
charts.py
─────────
Génération de graphiques PNG via matplotlib.
Source exclusive : SQLite (via database.py).

Graphiques générés :
  Utilisateur (2) :
    01 — Camembert des genres regardés par l'utilisateur
    02 — Timeline des notes dans le temps

  Pearson (2) :
    03 — Matrice Pearson inter-genres (corrélation de goûts globale)
    04 — Bar chart des scores Pearson : top voisins de l'utilisateur

  K-Means (2) :
    05 — Scatter K-Means projection PCA 2D + heatmap profil par cluster
    06 — Bar chart répartition des clusters (global)

Usage :
    python charts.py                     → génère tous les graphiques
    python charts.py --user ALICE-0001   → inclut les graphiques utilisateur
"""

import os
import sys
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from collections import defaultdict, Counter
from datetime import datetime

# ── import base de données locale ─────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import database

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

ALL_GENRES = ["action", "animation", "comedy", "drama",
              "horror", "romance", "sci-fi", "thriller"]

PALETTE = {
    "action":    "#E63946",
    "animation": "#F4A261",
    "comedy":    "#2A9D8F",
    "drama":     "#457B9D",
    "horror":    "#6A0572",
    "romance":   "#F77F00",
    "sci-fi":    "#1D3557",
    "thriller":  "#E9C46A",
}

CLUSTER_COLORS = ["#E63946", "#2A9D8F", "#F4A261", "#457B9D",
                  "#6A0572", "#F77F00", "#1D3557", "#E9C46A"]


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _save(fig, name: str) -> str:
    path = os.path.join(OUTPUT_DIR, name)
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"    ✓ {name}")
    return path


def _style(ax, title="", xlabel="", ylabel=""):
    ax.set_title(title, fontsize=12, fontweight="bold", pad=10)
    ax.set_xlabel(xlabel, fontsize=10)
    ax.set_ylabel(ylabel, fontsize=10)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(True, linestyle="--", alpha=0.35)


def _load_all_rows() -> list:
    """
    Charge toutes les notes depuis SQLite et les enrichit avec les métadonnées films.
    Retourne une liste de dicts plats.
    """
    conn = database.get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT r.user_id, r.movie, r.rating, r.timestamp,
               m.genre, m.director, m.year, m.duration_min, m.pace
        FROM ratings r
        LEFT JOIN movies m ON r.movie = m.title
        WHERE m.genre IS NOT NULL;
    """)
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows


def _build_user_genre_matrix(rows: list) -> tuple:
    """
    Retourne (user_ids, matrix) où matrix[i][j] = note moyenne
    de l'utilisateur i pour le genre j (0 si aucune note).
    """
    ug = defaultdict(lambda: defaultdict(list))
    for r in rows:
        ug[r["user_id"]][r["genre"]].append(r["rating"])

    user_ids = list(ug.keys())
    matrix   = np.array(
        [[np.mean(ug[uid].get(g, [0])) for g in ALL_GENRES] for uid in user_ids],
        dtype=float
    )
    return user_ids, matrix, ug


# ══════════════════════════════════════════════════════════════════════════════
# GRAPHIQUES UTILISATEUR
# ══════════════════════════════════════════════════════════════════════════════

def plot_user_genre_pie(user_id: str, user_name: str) -> str:
    """
    01 — Camembert de la distribution des genres regardés par l'utilisateur.
    """
    data = database.get_genre_distribution(user_id)
    if not data:
        print(f"  ⚠  Pas de données pour {user_name}.")
        return ""

    counts = {g: c for g, c in data.items()}
    labels = list(counts.keys())
    values = list(counts.values())
    colors = [PALETTE.get(g, "#999999") for g in labels]

    fig, ax = plt.subplots(figsize=(7, 6))
    wedges, _, autotexts = ax.pie(
        values, labels=None, autopct="%1.1f%%",
        colors=colors, startangle=140, pctdistance=0.80,
        wedgeprops=dict(edgecolor="white", linewidth=2)
    )
    for at in autotexts:
        at.set_fontsize(9)
        at.set_fontweight("bold")

    patches = [mpatches.Patch(color=PALETTE.get(g, "#999"), label=f"{g.upper()}  ({c} film{'s' if c > 1 else ''})")
               for g, c in counts.items()]
    ax.legend(handles=patches, fontsize=9, loc="lower left",
              framealpha=0.8, edgecolor="lightgray")
    ax.set_title(f"Genres regardés — {user_name.upper()}", fontsize=13, fontweight="bold")
    fig.tight_layout()
    return _save(fig, f"01_user_{user_name.lower()}_genres.png")


def plot_user_ratings_timeline(user_id: str, user_name: str) -> str:
    """
    02 — Évolution des notes dans le temps pour l'utilisateur.
         Points annotés avec le titre du film.
    """
    data = database.get_ratings_over_time(user_id)
    if len(data) < 2:
        print(f"  ⚠  Pas assez de données timeline pour {user_name}.")
        return ""

    # Détails film par film (pas agrégés par jour)
    conn = database.get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT r.movie, r.rating, r.timestamp
        FROM ratings r
        WHERE r.user_id = ? AND r.timestamp IS NOT NULL
        ORDER BY r.timestamp ASC;
    """, (user_id,))
    detail_rows = [dict(r) for r in cursor.fetchall()]
    conn.close()

    if len(detail_rows) < 2:
        print(f"  ⚠  Pas assez d'entrées détaillées pour {user_name}.")
        return ""

    dates   = [datetime.strptime(r["timestamp"][:10], "%Y-%m-%d") for r in detail_rows]
    ratings = [r["rating"] for r in detail_rows]
    titles  = [r["movie"] for r in detail_rows]

    fig, ax = plt.subplots(figsize=(13, 5))
    ax.plot(dates, ratings, color="#1D3557", linewidth=2,
            marker="o", markersize=8,
            markerfacecolor="#E63946", markeredgecolor="white", markeredgewidth=1.5,
            zorder=3)
    ax.fill_between(dates, ratings, alpha=0.10, color="#1D3557")

    for date, rating, title in zip(dates, ratings, titles):
        short = (title[:15] + "…") if len(title) > 15 else title
        ax.annotate(short, (date, rating),
                    textcoords="offset points", xytext=(0, 12),
                    ha="center", fontsize=7, rotation=30, color="#333")

    # Ligne de tendance linéaire
    x_num = np.array([(d - dates[0]).days for d in dates], dtype=float)
    if len(x_num) >= 2:
        slope, intercept, r_val, *_ = _linregress(x_num, ratings)
        y_trend = slope * x_num + intercept
        ax.plot(dates, y_trend, linestyle="--", color="#F4A261",
                linewidth=1.5, label=f"Tendance (r={r_val:.2f})")
        ax.legend(fontsize=9)

    ax.set_ylim(0.5, 5.8)
    ax.set_yticks([1, 2, 3, 4, 5])
    ax.axhline(np.mean(ratings), linestyle=":", color="#2A9D8F",
               linewidth=1.2, label=f"Moy. {np.mean(ratings):.2f}")
    _style(ax, f"Évolution des notes — {user_name.upper()}", "Date", "Note /5")
    fig.autofmt_xdate()
    fig.tight_layout()
    return _save(fig, f"02_user_{user_name.lower()}_timeline.png")


def _linregress(x, y):
    """Régression linéaire simple sans scipy."""
    n   = len(x)
    mx  = np.mean(x); my = np.mean(y)
    ss  = np.sum((x - mx) ** 2)
    if ss == 0:
        return 0, my, 0
    slope     = np.sum((x - mx) * (y - my)) / ss
    intercept = my - slope * mx
    y_pred    = slope * x + intercept
    ss_res    = np.sum((y - y_pred) ** 2)
    ss_tot    = np.sum((y - my) ** 2)
    r_val     = np.sqrt(max(0, 1 - ss_res / ss_tot)) if ss_tot > 0 else 0
    return slope, intercept, r_val


# ══════════════════════════════════════════════════════════════════════════════
# GRAPHIQUE PEARSON 03 — Matrice inter-genres (globale)
# ══════════════════════════════════════════════════════════════════════════════

def plot_pearson_genre_matrix(rows: list) -> str:
    """
    03 — Matrice de corrélation Pearson inter-genres.
         Chaque cellule = corrélation entre la note moyenne du genre A
         et celle du genre B, calculée sur tous les utilisateurs.
    """
    ug = defaultdict(lambda: defaultdict(list))
    for r in rows:
        ug[r["user_id"]][r["genre"]].append(r["rating"])

    user_ids = list(ug.keys())
    n        = len(ALL_GENRES)
    # Vecteur par genre : note moyenne par utilisateur (nan si absent)
    gv = {
        g: np.array([np.mean(ug[uid][g]) if ug[uid].get(g) else np.nan
                     for uid in user_ids])
        for g in ALL_GENRES
    }

    corr_matrix = np.zeros((n, n))
    for i, g1 in enumerate(ALL_GENRES):
        for j, g2 in enumerate(ALL_GENRES):
            v1, v2 = gv[g1], gv[g2]
            mask   = ~(np.isnan(v1) | np.isnan(v2))
            if mask.sum() >= 3:
                corr_matrix[i, j] = _pearson_np(v1[mask], v2[mask])

    fig, ax = plt.subplots(figsize=(9, 8))
    im = ax.imshow(corr_matrix, cmap="RdBu_r", vmin=-1, vmax=1, aspect="auto")

    ax.set_xticks(range(n))
    ax.set_yticks(range(n))
    ax.set_xticklabels([g.upper() for g in ALL_GENRES], rotation=35, ha="right", fontsize=9)
    ax.set_yticklabels([g.upper() for g in ALL_GENRES], fontsize=9)

    for i in range(n):
        for j in range(n):
            val   = corr_matrix[i, j]
            color = "white" if abs(val) > 0.5 else "black"
            ax.text(j, i, f"{val:.2f}", ha="center", va="center",
                    fontsize=8, color=color, fontweight="bold")

    plt.colorbar(im, ax=ax, label="Pearson r", shrink=0.8)
    ax.set_title("Matrice de corrélation Pearson inter-genres\n"
                 "(note moyenne par utilisateur sur toute la base)",
                 fontsize=12, fontweight="bold")
    fig.tight_layout()
    return _save(fig, "03_pearson_genre_matrix.png")


def _pearson_np(x: np.ndarray, y: np.ndarray) -> float:
    if len(x) < 2:
        return 0.0
    mx, my = x.mean(), y.mean()
    num    = np.sum((x - mx) * (y - my))
    den    = np.sqrt(np.sum((x - mx) ** 2)) * np.sqrt(np.sum((y - my) ** 2))
    return float(num / den) if den != 0 else 0.0


# ══════════════════════════════════════════════════════════════════════════════
# GRAPHIQUE PEARSON 04 — Top voisins de l'utilisateur
# ══════════════════════════════════════════════════════════════════════════════

def plot_pearson_user_neighbors(user_id: str, user_name: str) -> str:
    """
    04 — Bar chart horizontal des scores Pearson de l'utilisateur
         avec ses voisins de cluster (du plus similaire au moins similaire).
         Barres colorées selon le signe du score.
    """
    data = database.get_pearson_matrix_for_user(user_id, max_neighbors=12)
    if not data or not data.get("scores"):
        print(f"  ⚠  Pas de données Pearson pour {user_name} (clustering absent ?).")
        return ""

    scores   = data["scores"]
    names    = [s["name"] for s in scores]
    values   = [s["score"] for s in scores]
    commons  = [s["common_movies"] for s in scores]
    cluster  = data["cluster_id"]

    colors = ["#2A9D8F" if v >= 0.5 else "#F4A261" if v >= 0 else "#E63946"
              for v in values]

    fig, ax = plt.subplots(figsize=(9, max(4, len(names) * 0.55 + 1.5)))
    bars = ax.barh(names, values, color=colors, edgecolor="white", height=0.65)

    for bar, v, c in zip(bars, values, commons):
        sign    = 1 if v >= 0 else -1
        x_text  = v + sign * 0.02
        ha      = "left" if v >= 0 else "right"
        ax.text(x_text, bar.get_y() + bar.get_height() / 2,
                f"{v:+.3f}  ({c} film{'s' if c > 1 else ''} commun{'s' if c > 1 else ''})",
                va="center", ha=ha, fontsize=8.5, color="#222")

    ax.axvline(0, color="#333", linewidth=0.8)
    ax.set_xlim(-1.1, 1.35)
    ax.set_xlabel("Score de Pearson  (−1 = opposé, +1 = identique)", fontsize=10)

    legend_patches = [
        mpatches.Patch(color="#2A9D8F", label="Forte affinité  (≥ 0.5)"),
        mpatches.Patch(color="#F4A261", label="Affinité modérée  (0 – 0.5)"),
        mpatches.Patch(color="#E63946", label="Goûts opposés  (< 0)"),
    ]
    ax.legend(handles=legend_patches, fontsize=8.5, loc="lower right")
    _style(ax,
           f"Corrélation Pearson — {user_name.upper()} vs ses voisins (Cluster #{cluster})",
           "Score de Pearson", "Voisin")
    ax.invert_yaxis()
    fig.tight_layout()
    return _save(fig, f"04_pearson_user_{user_name.lower()}_neighbors.png")


# ══════════════════════════════════════════════════════════════════════════════
# GRAPHIQUE K-MEANS 05 — Scatter PCA 2D + heatmap profil
# ══════════════════════════════════════════════════════════════════════════════

def plot_kmeans_scatter(rows: list, highlight_user_id: str = None,
                        highlight_name: str = None) -> str:
    """
    05 — Côte à côte :
         • Scatter plot K-Means projection PCA 2D (un point = un utilisateur)
         • Heatmap : profil de note moyen par cluster × genre
         L'utilisateur courant est mis en évidence (étoile noire).
    """
    user_ids, matrix, ug = _build_user_genre_matrix(rows)
    if len(user_ids) < 4:
        print("  ⚠  Pas assez d'utilisateurs pour le K-Means.")
        return ""

    # Lecture des clusters depuis la base (déjà calculés)
    conn = database.get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, cluster_id FROM user_clusters;")
    cluster_map = {r["user_id"]: r["cluster_id"] for r in cursor.fetchall()}
    conn.close()

    labels    = np.array([cluster_map.get(uid, 0) for uid in user_ids])
    N_clusters = len(set(labels))

    # Projection PCA 2D manuelle (SVD)
    centered = matrix - matrix.mean(axis=0)
    std      = centered.std(axis=0)
    std[std == 0] = 1
    whitened = centered / std
    _, _, Vt = np.linalg.svd(whitened, full_matrices=False)
    proj     = whitened @ Vt[:2].T

    fig, axes = plt.subplots(1, 2, figsize=(15, 6))

    # ── Scatter ───────────────────────────────────────────────────────────────
    ax = axes[0]
    for k in range(N_clusters):
        mask = labels == k
        color = CLUSTER_COLORS[k % len(CLUSTER_COLORS)]
        ax.scatter(proj[mask, 0], proj[mask, 1],
                   c=color, s=70, alpha=0.75,
                   edgecolors="white", linewidths=0.8,
                   label=f"Cluster {k}  (n={mask.sum()})")

        # Centroïde du cluster
        cx, cy = proj[mask, 0].mean(), proj[mask, 1].mean()
        ax.scatter(cx, cy, c=color, s=200, marker="D",
                   edgecolors="black", linewidths=1.2, zorder=5)

    # Mise en évidence de l'utilisateur courant
    if highlight_user_id and highlight_user_id in user_ids:
        idx_h = user_ids.index(highlight_user_id)
        ax.scatter(proj[idx_h, 0], proj[idx_h, 1],
                   c="black", s=250, marker="*",
                   edgecolors="yellow", linewidths=1.5, zorder=6,
                   label=f"▶ {highlight_name or highlight_user_id}")

    ax.legend(fontsize=8.5, loc="upper right")
    _style(ax, "K-Means (K=4) — Projection PCA 2D\n(◆ = centroïde, vous)",
           "Composante principale 1", "Composante principale 2")

    # ── Heatmap profil par cluster ────────────────────────────────────────────
    ax2 = axes[1]
    cm_profile = np.zeros((N_clusters, len(ALL_GENRES)))
    for k in range(N_clusters):
        mask = labels == k
        if mask.sum() > 0:
            cm_profile[k] = matrix[mask].mean(axis=0)

    im = ax2.imshow(cm_profile, aspect="auto", cmap="YlOrRd", vmin=0, vmax=5)
    ax2.set_xticks(range(len(ALL_GENRES)))
    ax2.set_xticklabels([g.upper() for g in ALL_GENRES], rotation=35, ha="right", fontsize=9)
    ax2.set_yticks(range(N_clusters))
    ax2.set_yticklabels([f"Cluster {k}" for k in range(N_clusters)], fontsize=9)

    for i in range(N_clusters):
        for j in range(len(ALL_GENRES)):
            val   = cm_profile[i, j]
            color = "white" if val > 3.5 else "black"
            ax2.text(j, i, f"{val:.1f}", ha="center", va="center",
                     fontsize=8, color=color)

    plt.colorbar(im, ax=ax2, label="Note moyenne /5", shrink=0.8)
    ax2.set_title("Profil de goût moyen par cluster\n(note moyenne par genre)",
                  fontsize=11, fontweight="bold")

    fig.suptitle("Analyse K-Means des profils utilisateurs", fontsize=14,
                 fontweight="bold", y=1.01)
    fig.tight_layout()
    return _save(fig, "05_kmeans_pca_heatmap.png")


# ══════════════════════════════════════════════════════════════════════════════
# GRAPHIQUE K-MEANS 06 — Répartition globale des clusters
# ══════════════════════════════════════════════════════════════════════════════

def plot_kmeans_global(rows: list) -> str:
    """
    06 — Côte à côte :
         • Bar chart des tailles de clusters
         • Stacked bar : composition en genres de chaque cluster
    """
    data = database.get_kmeans_global_viz()
    if not data or not data.get("cluster_sizes"):
        print("  ⚠  Pas de données K-Means globales.")
        return ""

    cluster_sizes  = data["cluster_sizes"]
    dominant_genres = data["dominant_genres"]
    avg_ratings    = data["avg_ratings"]
    genre_breakdown = data["genre_breakdown"]
    cluster_ids    = sorted(cluster_sizes.keys())
    total_users    = data["total_users"]

    fig, axes = plt.subplots(1, 2, figsize=(14, 6))

    # ── Bar chart tailles ─────────────────────────────────────────────────────
    ax = axes[0]
    sizes  = [cluster_sizes[k] for k in cluster_ids]
    colors = [CLUSTER_COLORS[k % len(CLUSTER_COLORS)] for k in cluster_ids]
    x      = np.arange(len(cluster_ids))
    bars   = ax.bar(x, sizes, color=colors, edgecolor="white", width=0.55, zorder=3)

    for bar, size, k in zip(bars, sizes, cluster_ids):
        pct  = size / total_users * 100
        avg  = avg_ratings.get(k, 0)
        dom  = dominant_genres.get(k, "?")
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.3,
                f"{size}\n({pct:.0f}%)", ha="center", fontsize=9, fontweight="bold")
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() / 2,
                f"*{avg:.1f}\n{dom.upper()}", ha="center", va="center",
                fontsize=8, color="white", fontweight="bold")

    ax.set_xticks(x)
    ax.set_xticklabels([f"Cluster {k}" for k in cluster_ids], fontsize=10)
    ax.set_ylabel("Nombre d'utilisateurs", fontsize=10)
    _style(ax, f"Répartition des {total_users} utilisateurs par cluster\n"
               "(⭐ = note moy. | genre dominant)",
           "Cluster", "Utilisateurs")

    # ── Stacked bar composition genres ───────────────────────────────────────
    ax2 = axes[1]
    # Reconstitution des pourcentages par genre pour chaque cluster
    bottom = np.zeros(len(cluster_ids))
    legend_patches = []

    for genre in ALL_GENRES:
        vals  = [genre_breakdown.get(k, {}).get(genre, 0) for k in cluster_ids]
        color = PALETTE.get(genre, "#999999")
        ax2.bar(x, vals, bottom=bottom, color=color, edgecolor="white",
                width=0.55, label=genre.upper(), zorder=3)
        for xi, (v, b) in enumerate(zip(vals, bottom)):
            if v >= 8:
                ax2.text(x[xi], b + v / 2, f"{v:.0f}%",
                         ha="center", va="center", fontsize=7,
                         color="white", fontweight="bold")
        bottom += np.array(vals)
        if any(v > 0 for v in vals):
            legend_patches.append(mpatches.Patch(color=color, label=genre.upper()))

    ax2.set_xticks(x)
    ax2.set_xticklabels([f"Cluster {k}" for k in cluster_ids], fontsize=10)
    ax2.set_ylabel("% des films notés", fontsize=10)
    ax2.legend(handles=legend_patches, fontsize=7.5, loc="upper right",
               framealpha=0.8, ncol=2)
    _style(ax2, "Composition en genres de chaque cluster\n(% des films notés par cluster)",
           "Cluster", "% genres")

    fig.suptitle("Analyse K-Means — Vue globale", fontsize=14,
                 fontweight="bold", y=1.01)
    fig.tight_layout()
    return _save(fig, "06_kmeans_global.png")


# ══════════════════════════════════════════════════════════════════════════════
# POINT D'ENTRÉE
# ══════════════════════════════════════════════════════════════════════════════

def run_all_charts(user_id: str = None, user_name: str = None):
    """
    Génère tous les graphiques.
    Si user_id est fourni, génère aussi les 2 graphiques personnalisés.
    """
    print("\n  ┌─ Chargement des données SQLite…")
    rows = _load_all_rows()
    n_users  = len(set(r["user_id"] for r in rows))
    n_movies = len(set(r["movie"] for r in rows))
    print(f"  │  {len(rows)} notes  |  {n_users} utilisateurs  |  {n_movies} films")
    print("  ├─ Génération des graphiques…")

    paths = []

    # ── Graphiques utilisateur ─────────────────────────────────────────────
    if user_id:
        print(f"  │  [Utilisateur : {user_name or user_id}]")
        p = plot_user_genre_pie(user_id, user_name or user_id)
        if p: paths.append(p)
        p = plot_user_ratings_timeline(user_id, user_name or user_id)
        if p: paths.append(p)
        p = plot_pearson_user_neighbors(user_id, user_name or user_id)
        if p: paths.append(p)

    # ── Graphiques globaux ─────────────────────────────────────────────────
    p = plot_pearson_genre_matrix(rows)
    if p: paths.append(p)

    p = plot_kmeans_scatter(rows,
                             highlight_user_id=user_id,
                             highlight_name=user_name)
    if p: paths.append(p)

    p = plot_kmeans_global(rows)
    if p: paths.append(p)

    print(f"  └─ {len(paths)} graphique(s) générés dans : {OUTPUT_DIR}/")
    return paths


if __name__ == "__main__":
    database.create_tables()

    # Lecture optionnelle d'une clé de session en argument
    user_id   = None
    user_name = None

    if "--user" in sys.argv:
        idx = sys.argv.index("--user")
        if idx + 1 < len(sys.argv):
            session_code = sys.argv[idx + 1]
            user = database.find_user_by_code(session_code)
            if user:
                user_id   = user["user_id"]
                user_name = user["name"]
                print(f"\n  Utilisateur détecté : {user_name} (ID {user_id})")
            else:
                print(f"\n  ⚠  Clé de session inconnue : {session_code}")

    run_all_charts(user_id=user_id, user_name=user_name)