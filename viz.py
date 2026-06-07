"""
viz.py
──────
Visualisations console (ASCII) — aucune dépendance externe.

Graphiques disponibles :
  1. Distribution des genres regardés             (barres horizontales)
  2. Évolution de la note moyenne dans le temps   (courbe ASCII)
  3. Corrélation de Pearson — vue utilisateur     (tableau de scores vs voisins)
  4. Corrélation de Pearson — vue globale         (top paires similaires)
  5. Clusters K-Means — vue utilisateur           (qui sont mes voisins de cluster)
  6. Clusters K-Means — vue globale               (répartition de toute la base)
"""
import database
from collections import defaultdict

# ══════════════════════════════════════════════════════════════════════════════
# CONSTANTES VISUELLES
# ══════════════════════════════════════════════════════════════════════════════

BAR_CHAR   = "█"
EMPTY_CHAR = "░"
BAR_WIDTH  = 35

GENRE_COLORS = {
    "sci-fi":    "🔵", "action":    "🔴", "thriller":  "🟠",
    "drama":     "🟤", "animation": "🟢", "horror":    "⚫",
    "romance":   "🩷", "comedy":    "🟡",
}

CLUSTER_SYMBOLS = ["◆", "●", "▲", "■", "★", "✦", "◉", "⬟"]

def _bar(value, max_val, width=BAR_WIDTH) -> str:
    filled = int(value / max_val * width) if max_val else 0
    return BAR_CHAR * filled + EMPTY_CHAR * (width - filled)

def _score_bar(score: float, width=20) -> str:
    """Barre de -1.0 à +1.0 centrée sur 0."""
    mid   = width // 2
    if score >= 0:
        filled = int(score * mid)
        return " " * mid + BAR_CHAR * filled + EMPTY_CHAR * (mid - filled)
    else:
        filled = int(abs(score) * mid)
        return EMPTY_CHAR * (mid - filled) + "▒" * filled + " " * mid

def _score_color(score: float) -> str:
    if score >= 0.6:  return "🟢"
    if score >= 0.3:  return "🟡"
    if score >= 0.0:  return "🟠"
    return "🔴"


# ══════════════════════════════════════════════════════════════════════════════
# GRAPHIQUE 1 : DISTRIBUTION DES GENRES
# ══════════════════════════════════════════════════════════════════════════════

def show_genre_distribution(user_id: str):
    data = database.get_genre_distribution(user_id)

    print("\n" + "═"*65)
    print(" 📊  DISTRIBUTION DE VOS GENRES REGARDÉS")
    print("═"*65)

    if not data:
        print("  ℹ️  Notez des films pour voir vos statistiques.")
        print("═"*65)
        return

    total     = sum(data.values())
    max_count = max(data.values())

    for genre, count in sorted(data.items(), key=lambda x: x[1], reverse=True):
        pct   = count / total * 100
        bar   = _bar(count, max_count)
        icon  = GENRE_COLORS.get(genre, "⬜")
        label = genre.upper().ljust(10)
        print(f"  {icon} {label} │{bar}│ {count:>3} film(s)  {pct:>5.1f}%")

    print("─"*65)
    print(f"  Total : {total} film(s) évalué(s) sur {len(data)} genre(s)")
    print("═"*65)


# ══════════════════════════════════════════════════════════════════════════════
# GRAPHIQUE 2 : ÉVOLUTION DES NOTES DANS LE TEMPS
# ══════════════════════════════════════════════════════════════════════════════

def show_ratings_over_time(user_id: str):
    data = database.get_ratings_over_time(user_id)

    print("\n" + "═"*65)
    print(" 📈  ÉVOLUTION DE VOS NOTES AU FIL DU TEMPS")
    print("═"*65)

    if not data:
        print("  ℹ️  Notez des films pour voir la tendance.")
        print("═"*65)
        return

    if len(data) == 1:
        d = data[0]
        print(f"  Une seule session le {d['day']} — Note moyenne : {d['avg_rating']:.1f}/5")
        print("═"*65)
        return

    ROWS   = 10
    COLS   = min(len(data), 40)
    step   = max(1, len(data) // COLS)
    points = data[::step][:COLS]
    y_min, y_max = 1.0, 5.0
    grid = [[" " for _ in range(COLS)] for _ in range(ROWS)]

    for col_idx, point in enumerate(points):
        avg     = max(y_min, min(y_max, point["avg_rating"]))
        row_idx = ROWS - 1 - int((avg - y_min) / (y_max - y_min) * (ROWS - 1))
        grid[max(0, min(ROWS-1, row_idx))][col_idx] = "●"

    for col_idx in range(1, len(points)):
        avg_prev = max(y_min, min(y_max, points[col_idx-1]["avg_rating"]))
        avg_curr = max(y_min, min(y_max, points[col_idx]["avg_rating"]))
        r_prev   = max(0, min(ROWS-1, ROWS-1 - int((avg_prev-y_min)/(y_max-y_min)*(ROWS-1))))
        r_curr   = max(0, min(ROWS-1, ROWS-1 - int((avg_curr-y_min)/(y_max-y_min)*(ROWS-1))))
        if r_prev == r_curr:
            if grid[r_prev][col_idx] == " ": grid[r_prev][col_idx] = "─"
        else:
            for r in range(min(r_prev, r_curr)+1, max(r_prev, r_curr)):
                if grid[r][col_idx] == " ": grid[r][col_idx] = "│"

    print()
    for row_idx, row in enumerate(grid):
        y_val = y_max - (row_idx / (ROWS-1)) * (y_max - y_min)
        y_lbl = f"{y_val:.1f}" if row_idx % 2 == 0 else "    "
        print(f"  {y_lbl} │ {''.join(row)}")
    print("       └" + "─" * COLS)

    if points:
        d_start = points[0]["day"]
        d_end   = points[-1]["day"]
        gap     = max(1, COLS - len(d_start) - len(d_end) - 2)
        print(f"        {d_start}{' ' * gap}{d_end}")

    all_r      = [p["avg_rating"] for p in points]
    avg_global = sum(all_r) / len(all_r)
    trend      = ("📈 En hausse" if all_r[-1] > all_r[0] else
                  "📉 En baisse" if all_r[-1] < all_r[0] else "➡️  Stable")
    print()
    print("─"*65)
    print(f"  Note moyenne globale : {avg_global:.2f}/5   |   Tendance : {trend}")
    print(f"  Période              : {data[0]['day']}  →  {data[-1]['day']}")
    print("═"*65)


# ══════════════════════════════════════════════════════════════════════════════
# GRAPHIQUE 3 : PEARSON — VUE UTILISATEUR (moi vs mes voisins de cluster)
# ══════════════════════════════════════════════════════════════════════════════

def show_pearson_user(user_id: str):
    data = database.get_pearson_matrix_for_user(user_id)

    print("\n" + "═"*70)
    print(" 🔗  CORRÉLATION DE PEARSON — VOS AFFINITÉS AVEC VOS VOISINS")
    print("═"*70)

    if not data:
        print("  ℹ️  Le moteur IA n'est pas encore actif (pas de cluster calculé).")
        print("  💡  Lancez des recommandations et notez des films pour activer ce graphique.")
        print("═"*70)
        return

    scores = data.get("scores", [])
    if not scores:
        print("  ℹ️  Aucun voisin de cluster trouvé pour cet utilisateur.")
        print("═"*70)
        return

    user_name  = data["user_name"]
    cluster_id = data["cluster_id"]

    print(f"\n  Utilisateur : {user_name.upper()}  │  Cluster #{cluster_id}")
    print(f"\n  {'Voisin':<18} │ {'Score Pearson':^8} │ {'Films communs':^13} │ Barre [-1.0 ──── 0 ──── +1.0]")
    print("  " + "─"*18 + "─┼─" + "─"*8 + "─┼─" + "─"*13 + "─┼─" + "─"*42)

    for s in scores:
        name    = s["name"][:17].ljust(18)
        score   = s["score"]
        common  = s["common_movies"]
        icon    = _score_color(score)
        bar     = _score_bar(score, width=40)
        print(f"  {name} │ {icon} {score:>+.3f}  │ {common:^13} │ {bar}")

    # Résumé
    valid = [s["score"] for s in scores if s["common_movies"] >= 2]
    if valid:
        best   = max(scores, key=lambda x: x["score"])
        avg_sc = sum(valid) / len(valid)
        print()
        print("─"*70)
        print(f"  Meilleure affinité : {best['name']} ({best['score']:+.3f}) — {best['common_movies']} films en commun")
        print(f"  Score moyen        : {avg_sc:+.3f}  sur {len(scores)} voisins analysés")
        print()
        print("  Légende :  🟢 Forte corrélation (≥0.6)  🟡 Modérée (≥0.3)")
        print("             🟠 Faible (≥0.0)             🔴 Négative (<0.0)")
    print("═"*70)


# ══════════════════════════════════════════════════════════════════════════════
# GRAPHIQUE 4 : PEARSON — VUE GLOBALE (top paires similaires)
# ══════════════════════════════════════════════════════════════════════════════

def show_pearson_global():
    pairs = database.get_pearson_top_pairs_global(limit=12)

    print("\n" + "═"*70)
    print(" 🌐  CORRÉLATION DE PEARSON — TOP AFFINITÉS GLOBALES (Toute la base)")
    print("═"*70)

    if not pairs:
        print("  ℹ️  Pas assez d'utilisateurs avec suffisamment de notes communes.")
        print("═"*70)
        return

    print(f"\n  {'Rang':<5} {'Utilisateur A':<16} {'Utilisateur B':<16} {'Score':^8} {'Films':<8} Affinité")
    print("  " + "─"*5 + "─" + "─"*16 + "─" + "─"*16 + "─" + "─"*8 + "─" + "─"*8 + "─" + "─"*15)

    for idx, pair in enumerate(pairs, 1):
        icon  = _score_color(pair["score"])
        a     = pair["user_a"][:15].ljust(16)
        b     = pair["user_b"][:15].ljust(16)
        score = pair["score"]
        films = pair["common_movies"]
        bar   = BAR_CHAR * int(max(0, score) * 12) + EMPTY_CHAR * (12 - int(max(0, score) * 12))
        print(f"  #{idx:<4} {a} {b} {icon} {score:>+.3f}  {films:<8} {bar}")

    # Distribution des scores
    positive = sum(1 for p in pairs if p["score"] > 0.5)
    negative = sum(1 for p in pairs if p["score"] < 0)
    print()
    print("─"*70)
    print(f"  Paires analysées    : {len(pairs)}")
    print(f"  Forte corrélation   : {positive} paire(s) (score > 0.5)")
    print(f"  Corrélation négative: {negative} paire(s)")
    print("═"*70)


# ══════════════════════════════════════════════════════════════════════════════
# GRAPHIQUE 5 : K-MEANS — VUE UTILISATEUR (mon cluster et mes voisins)
# ══════════════════════════════════════════════════════════════════════════════

def show_kmeans_user(user_id: str):
    data = database.get_kmeans_viz_data(user_id)

    print("\n" + "═"*70)
    print(" 🧩  CLUSTERING K-MEANS — VOTRE POSITION DANS LES GROUPES")
    print("═"*70)

    if not data:
        print("  ℹ️  Clustering non disponible (pas encore calculé).")
        print("  💡  Le clustering se déclenche automatiquement au seuil IA.")
        print("═"*70)
        return

    user_cluster   = data["user_cluster"]
    cluster_sizes  = data["cluster_sizes"]
    dominant_genres = data["dominant_genres"]
    neighbors      = data["neighbors"]
    total_clusters = data["total_clusters"]
    user_name      = data["user_name"]
    total_users    = sum(cluster_sizes.values())

    # Carte des clusters
    print(f"\n  {user_name.upper()} est dans le Cluster #{user_cluster}")
    print(f"  ({total_users} utilisateurs répartis en {total_clusters} clusters)\n")
    print(f"  {'Cluster':<10} {'Taille':^8} {'Genre dominant':<14} Répartition")
    print("  " + "─"*10 + "─" + "─"*8 + "─" + "─"*14 + "─" + "─"*30)

    max_size = max(cluster_sizes.values()) if cluster_sizes else 1
    for cid in sorted(cluster_sizes.keys()):
        size    = cluster_sizes[cid]
        genre   = dominant_genres.get(cid, "?")
        icon    = GENRE_COLORS.get(genre, "⬜")
        sym     = CLUSTER_SYMBOLS[cid % len(CLUSTER_SYMBOLS)]
        bar     = _bar(size, max_size, width=25)
        marker  = " ◀ VOUS" if cid == user_cluster else ""
        print(f"  {sym} #{cid:<7} {size:^8} {icon} {genre:<12} {bar}{marker}")

    # Voisins de mon cluster
    if neighbors:
        print(f"\n  👥 VOS VOISINS DANS LE CLUSTER #{user_cluster} :")
        print("  " + "─"*50)
        for i, nb in enumerate(neighbors, 1):
            genre_icon = GENRE_COLORS.get(nb["genre"], "⬜") if nb["genre"] else "⬜"
            print(f"    [{i:>2}] {nb['name']:<20} {genre_icon} {(nb['genre'] or '?').upper()}")
    else:
        print(f"\n  ℹ️  Vous êtes seul dans le Cluster #{user_cluster} pour l'instant.")

    print()
    print("─"*70)
    my_size = cluster_sizes.get(user_cluster, 0)
    pct     = my_size / total_users * 100 if total_users else 0
    print(f"  Votre cluster #{user_cluster} regroupe {my_size} utilisateur(s) ({pct:.1f}% de la base)")
    print(f"  Genre dominant de votre cluster : {dominant_genres.get(user_cluster, '?').upper()}")
    print("═"*70)


# ══════════════════════════════════════════════════════════════════════════════
# GRAPHIQUE 6 : K-MEANS — VUE GLOBALE (répartition de toute la base)
# ══════════════════════════════════════════════════════════════════════════════

def show_kmeans_global():
    data = database.get_kmeans_global_viz()

    print("\n" + "═"*70)
    print(" 🌐  CLUSTERING K-MEANS — VUE GLOBALE DE TOUS LES UTILISATEURS")
    print("═"*70)

    if not data or not data.get("cluster_sizes"):
        print("  ℹ️  Aucun cluster calculé. Lancez le pipeline ETL pour initialiser.")
        print("═"*70)
        return

    cluster_sizes   = data["cluster_sizes"]
    dominant_genres = data["dominant_genres"]
    avg_ratings     = data["avg_ratings"]
    genre_breakdown = data["genre_breakdown"]
    total_users     = data["total_users"]

    print(f"\n  {total_users} utilisateurs clusterisés en {len(cluster_sizes)} groupes\n")

    # Vue synthétique par cluster
    max_size = max(cluster_sizes.values())
    for cid in sorted(cluster_sizes.keys()):
        size    = cluster_sizes[cid]
        genre   = dominant_genres.get(cid, "?")
        avg_r   = avg_ratings.get(cid, 0.0)
        pct     = size / total_users * 100
        icon    = GENRE_COLORS.get(genre, "⬜")
        sym     = CLUSTER_SYMBOLS[cid % len(CLUSTER_SYMBOLS)]
        bar     = _bar(size, max_size, width=28)

        print(f"  {sym} CLUSTER #{cid}")
        print(f"     {bar} {size} utilisateurs ({pct:.1f}%)")
        print(f"     {icon} Genre dominant : {genre.upper():<12}  ⭐ Note moy. : {avg_r:.2f}/5")

        # Répartition des genres secondaires
        breakdown = genre_breakdown.get(cid, {})
        if breakdown:
            genre_parts = "  |  ".join(
                f"{GENRE_COLORS.get(g, '⬜')} {g.upper()} {v:.0f}%"
                for g, v in list(breakdown.items())[:4]
            )
            print(f"     Détail genres : {genre_parts}")
        print()

    # Graphique en barres horizontales de la taille des clusters
    print("─"*70)
    print("  COMPARAISON DES TAILLES DE CLUSTERS :\n")
    for cid in sorted(cluster_sizes.keys()):
        size = cluster_sizes[cid]
        pct  = size / total_users * 100
        bar  = _bar(size, max_size, width=35)
        sym  = CLUSTER_SYMBOLS[cid % len(CLUSTER_SYMBOLS)]
        print(f"  {sym} #{cid} │{bar}│ {size:>4} ({pct:>5.1f}%)")

    print()
    # Équilibre des clusters
    sizes = list(cluster_sizes.values())
    ideal = total_users / len(sizes)
    imbalance = max(abs(s - ideal) / ideal * 100 for s in sizes)
    balance_label = "✅ Bien équilibré" if imbalance < 25 else "⚠️  Déséquilibré"
    print(f"  Équilibre des clusters : {balance_label} (écart max : {imbalance:.0f}%)")
    print("═"*70)


# ══════════════════════════════════════════════════════════════════════════════
# MENU PRINCIPAL DES VISUALISATIONS
# ══════════════════════════════════════════════════════════════════════════════

def show_viz_menu(user_id: str):
    """Menu de sélection des visualisations, appelé depuis main.py."""
    while True:
        print("\n" + "═"*70)
        print(" 📊  TABLEAU DE BORD — ANALYSE DE VOS DONNÉES")
        print("═"*70)
        print(" ── Vos statistiques personnelles ──────────────────────────────")
        print(" [1] Distribution de vos genres regardés")
        print(" [2] Évolution de vos notes au fil du temps")
        print(" [3] Corrélation Pearson — mes affinités avec mes voisins")
        print(" [4] K-Means — ma position dans les clusters")
        print(" ── Vue globale sur tous les utilisateurs ───────────────────────")
        print(" [5] Corrélation Pearson — top paires similaires (base entière)")
        print(" [6] K-Means — répartition globale de tous les utilisateurs")
        print(" ── ─────────────────────────────────────────────────────────────")
        print(" [7] Tout afficher (6 graphiques)")
        print(" [Q] Retour au menu membre")
        print("═"*70)

        choice = input("Votre choix : ").strip().upper()

        if choice == "1":
            show_genre_distribution(user_id)
        elif choice == "2":
            show_ratings_over_time(user_id)
        elif choice == "3":
            show_pearson_user(user_id)
        elif choice == "4":
            show_kmeans_user(user_id)
        elif choice == "5":
            show_pearson_global()
        elif choice == "6":
            show_kmeans_global()
        elif choice == "7":
            show_genre_distribution(user_id)
            show_ratings_over_time(user_id)
            show_pearson_user(user_id)
            show_kmeans_user(user_id)
            show_pearson_global()
            show_kmeans_global()
        elif choice == "Q":
            break
        else:
            print("❌ Option invalide.")

        if choice in "1234567":
            input("\nAppuyez sur ENTRÉE pour continuer...")