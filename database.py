"""
database.py
───────────
Couche de persistance SQLite + Moteur de recommandation hybride.

Stratégie évolutive :
  Phase 1 — Système Expert  : < MATURITY_THRESHOLD films notés
             → Filtrage par tags/genres déclarés + règles métier (âge, pace)
             → Mode Découverte : diversification forcée sur 10 premières reco
  Phase 2 — Filtrage hybride: ≥ MATURITY_THRESHOLD films notés
             → Contenu (genre, réalisateur, pace) + Corrélation de Pearson
             + Clustering K-Means (héritage des voisins)
             + Exclusion âge automatique
"""
import sqlite3
import os
import math
import random
from collections import defaultdict

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "recommender.db")

# ── Seuil de bascule Système Expert → IA ──────────────────────────────────────
MATURITY_THRESHOLD = 5   # Abaissé à 5 pour la démo (50 en production)
CLUSTER_COUNT      = 4   # Nombre de clusters K-Means

SECRET_QUESTIONS = [
    "Comment s'appelait ton tout premier animal de compagnie ?",
    "Dans quelle ville as-tu grandi et passé ton enfance ?",
    "Quel est le premier modèle de voiture que tu as conduit ?",
    "Quel est le film culte qui t'a le plus marqué quand tu étais petit ?"
]


# ══════════════════════════════════════════════════════════════════════════════
# CONNEXION & INITIALISATION
# ══════════════════════════════════════════════════════════════════════════════

def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def create_tables():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON;")

    # ── Tables existantes ─────────────────────────────────────────────────────
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS movies (
        movie_id    TEXT PRIMARY KEY,
        title       TEXT UNIQUE NOT NULL,
        genre       TEXT NOT NULL,
        duration_min INTEGER,
        avg_rating  REAL,
        year        INTEGER,
        pace        TEXT,
        director    TEXT,
        description TEXT
    );""")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id        TEXT PRIMARY KEY,
        name           TEXT NOT NULL,
        age            INTEGER,
        profile_type   TEXT,
        session_code   TEXT UNIQUE NOT NULL,
        secret_question TEXT NOT NULL,
        secret_answer  TEXT NOT NULL
    );""")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS ratings (
        rating_id  INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id    TEXT NOT NULL,
        movie      TEXT NOT NULL,
        rating     REAL NOT NULL,
        timestamp  TEXT,
        source     TEXT,
        reason     TEXT,
        FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
        FOREIGN KEY (movie)   REFERENCES movies(title)  ON DELETE CASCADE
    );""")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS recommendations (
        user_id       TEXT,
        movie         TEXT,
        date_proposed TEXT
    );""")

    # ── Nouvelles tables ───────────────────────────────────────────────────────

    # Tags multi-genres déclarés à l'onboarding (remplace profile_type unique)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS user_tags (
        user_id TEXT NOT NULL,
        tag     TEXT NOT NULL,
        weight  REAL DEFAULT 1.0,
        FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
    );""")

    # Résultat du clustering K-Means (recalculé périodiquement)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS user_clusters (
        user_id    TEXT PRIMARY KEY,
        cluster_id INTEGER NOT NULL,
        updated_at TEXT,
        FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
    );""")

    # Historique d'exploration (phase Cold Start) pour la diversification
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS exploration_log (
        user_id    TEXT NOT NULL,
        movie      TEXT NOT NULL,
        shown_at   TEXT,
        FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
    );""")

    conn.commit()
    conn.close()


# ══════════════════════════════════════════════════════════════════════════════
# FONCTIONS UTILITAIRES DE BASE (inchangées)
# ══════════════════════════════════════════════════════════════════════════════

def get_all_unique_genres():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT genre FROM movies WHERE genre IS NOT NULL;")
    genres = [row["genre"] for row in cursor.fetchall()]
    conn.close()
    return genres


def find_user_by_code(session_code):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM users WHERE UPPER(TRIM(session_code)) = UPPER(TRIM(?));",
        (session_code,)
    )
    user = cursor.fetchone()
    conn.close()
    return user


def get_user_viewing_history(user_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT movie, rating, timestamp, source
        FROM ratings
        WHERE user_id = ?
        AND source IN ('system_expert_feedback', 'discovery_quiz')
        ORDER BY timestamp DESC LIMIT 10;
    """, (user_id,))
    history = cursor.fetchall()
    conn.close()
    return history


def save_recommendation(user_id, title):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO recommendations (user_id, movie, date_proposed) VALUES (?, ?, datetime('now'))",
        (user_id, title)
    )
    conn.commit()
    conn.close()


def register_new_user(user_id, name, age, profile_type, session_code, question, answer):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO users (user_id, name, age, profile_type, session_code, secret_question, secret_answer)
            VALUES (?, ?, ?, ?, ?, ?, ?);
        """, (user_id, name, age, profile_type, session_code.strip().upper(), question, answer.strip().lower()))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()


def has_already_rated(user_id, movie_title) -> bool:
    """Vérifie si l'utilisateur a déjà noté ce film."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT 1 FROM ratings WHERE user_id = ? AND movie = ? LIMIT 1;",
        (user_id, movie_title)
    )
    exists = cursor.fetchone() is not None
    conn.close()
    return exists


def save_user_feedback(user_id, movie_title, rating_value):
    import datetime
    # Anti-doublon : on refuse si le film a déjà été noté
    if has_already_rated(user_id, movie_title):
        return "already_rated"
    conn = get_connection()
    cursor = conn.cursor()
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        cursor.execute("""
            INSERT INTO ratings (user_id, movie, rating, timestamp, source, reason)
            VALUES (?, ?, ?, ?, 'system_expert_feedback', 'Évaluation de satisfaction post-recommandation');
        """, (user_id, movie_title, float(rating_value), now_str))
        conn.commit()
        return True
    except sqlite3.Error:
        return False
    finally:
        conn.close()


# ══════════════════════════════════════════════════════════════════════════════
# GESTION DES TAGS (multi-genres onboarding)
# ══════════════════════════════════════════════════════════════════════════════

def save_discovery_rating(user_id: str, movie_title: str, rating_value: float):
    """
    Enregistre une note issue du quiz de découverte (onboarding).
    source = 'discovery_quiz' — comptabilisée dans la maturité.
    """
    import datetime
    if has_already_rated(user_id, movie_title):
        return  # Pas de doublon
    conn = get_connection()
    cursor = conn.cursor()
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        cursor.execute("""
            INSERT INTO ratings (user_id, movie, rating, timestamp, source, reason)
            VALUES (?, ?, ?, ?, 'discovery_quiz', 'Note enregistrée lors du quiz de découverte');
        """, (user_id, movie_title, float(rating_value), now_str))
        conn.commit()
    except sqlite3.Error:
        pass
    finally:
        conn.close()


def save_user_tags(user_id, tags: list):
    """Enregistre les tags déclarés à l'onboarding. tag[0] a un poids de 2.0 (primaire)."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM user_tags WHERE user_id = ?;", (user_id,))
    for i, tag in enumerate(tags):
        weight = 2.0 if i == 0 else 1.0
        cursor.execute(
            "INSERT INTO user_tags (user_id, tag, weight) VALUES (?, ?, ?);",
            (user_id, tag.lower(), weight)
        )
    conn.commit()
    conn.close()


def get_user_tags(user_id) -> list:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT tag, weight FROM user_tags WHERE user_id = ? ORDER BY weight DESC;",
        (user_id,)
    )
    tags = [(row["tag"], row["weight"]) for row in cursor.fetchall()]
    conn.close()
    return tags


# ══════════════════════════════════════════════════════════════════════════════
# MATURITÉ DU PROFIL
# ══════════════════════════════════════════════════════════════════════════════

def get_user_maturity(user_id) -> dict:
    """
    Retourne un dictionnaire :
      - rating_count  : nombre de films notés
      - mode          : 'discovery' | 'expert' | 'ia'
      - is_ai_ready   : bool
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """SELECT COUNT(DISTINCT movie) as cnt FROM ratings
           WHERE user_id = ?
           AND source IN ('system_expert_feedback', 'discovery_quiz');""",
        (user_id,)
    )
    cnt = cursor.fetchone()["cnt"]
    conn.close()

    if cnt == 0:
        mode = "discovery"
    elif cnt < MATURITY_THRESHOLD:
        mode = "expert"
    else:
        mode = "ia"

    return {
        "rating_count": cnt,
        "mode": mode,
        "is_ai_ready": cnt >= MATURITY_THRESHOLD,
        "threshold": MATURITY_THRESHOLD,
        "progress_pct": min(100, int(cnt / MATURITY_THRESHOLD * 100))
    }

# ══════════════════════════════════════════════════════════════════════════════
# MOTEUR DE RECOMMANDATION — SÉLECTION AUTOMATIQUE
# ══════════════════════════════════════════════════════════════════════════════

def get_recommendations(user_id, profile_type, age, limit=5) -> tuple:
    """
    Point d'entrée unique. Retourne (liste_films, mode_utilisé).
    Délègue automatiquement selon la maturité.
    """
    maturity = get_user_maturity(user_id)
    mode = maturity["mode"]

    if mode == "discovery":
        movies = _recommend_discovery(user_id, profile_type, limit)
    elif mode == "expert":
        movies = _recommend_expert(user_id, profile_type, age, limit)
    else:
        movies = _recommend_ia(user_id, profile_type, age, limit)

    return movies, mode, maturity


# ── Phase 1a : Découverte (Cold Start) ────────────────────────────────────────

def _recommend_discovery(user_id, profile_type, limit=5) -> list:
    """
    Diversification forcée sur les premières recommandations.
    On tire des films de PLUSIEURS genres pour ne pas enfermer l'utilisateur.
    """
    conn = get_connection()
    cursor = conn.cursor()

    # Récupère les tags de l'utilisateur (s'ils existent), sinon profil par défaut
    tags = get_user_tags(user_id)
    if tags:
        genres = [t[0] for t in tags]
    else:
        genres = [profile_type]
        # Ajouter 2 genres aléatoires pour la diversification
        all_genres = get_all_unique_genres()
        extras = [g for g in all_genres if g != profile_type]
        random.shuffle(extras)
        genres += extras[:2]

    already_seen = _get_excluded_movies(cursor, user_id)
    placeholders_seen = ",".join("?" * len(already_seen)) if already_seen else "'__NONE__'"

    result = []
    per_genre = max(1, limit // len(genres))

    for genre in genres:
        if len(result) >= limit:
            break
        needed = min(per_genre, limit - len(result))
        # On prend un pool plus large pour varier (top 20) puis on mélange
        query = f"""
            SELECT title, avg_rating, director, year, duration_min, genre
            FROM movies
            WHERE genre = ?
            AND title NOT IN ({placeholders_seen if already_seen else "'__NONE__'"})
            AND avg_rating >= 3.5
            ORDER BY avg_rating DESC
            LIMIT 20;
        """
        params = [genre] + (already_seen if already_seen else [])
        cursor.execute(query, params)
        pool = [dict(r) for r in cursor.fetchall()]
        random.shuffle(pool)
        result += pool[:needed]

    conn.close()

    # Marque dans exploration_log
    _log_exploration(user_id, [m["title"] for m in result])
    return result


# ── Phase 1b : Système Expert ─────────────────────────────────────────────────

def _recommend_expert(user_id, profile_type, age, limit=5) -> list:
    """
    Filtrage par contenu : genre (via tags pondérés) + règles métier âge.
    Ajout d'un biais sur le réalisateur si l'utilisateur a déjà noté ≥ 4/5 un film.
    """
    conn = get_connection()
    cursor = conn.cursor()

    tags = get_user_tags(user_id)
    primary_genre = tags[0][0] if tags else profile_type.lower()

    # Réalisateur favori : si l'utilisateur a mis ≥ 4.0 à un film, on booste ce réalisateur
    cursor.execute("""
        SELECT m.director, AVG(r.rating) as avg_r
        FROM ratings r JOIN movies m ON r.movie = m.title
        WHERE r.user_id = ? AND r.rating >= 4.0
        GROUP BY m.director ORDER BY avg_r DESC LIMIT 1;
    """, (user_id,))
    fav_row = cursor.fetchone()
    fav_director = fav_row["director"] if fav_row else None

    already_seen = _get_excluded_movies(cursor, user_id)
    placeholders = ",".join("?" * len(already_seen)) if already_seen else "'__NONE__'"

    # Films du genre primaire — on tire un pool large pour varier les résultats
    query = f"""
        SELECT title, avg_rating, director, year, duration_min, genre,
               CASE WHEN director = ? THEN 1 ELSE 0 END as director_boost
        FROM movies
        WHERE genre = ?
        AND title NOT IN ({placeholders if already_seen else "'__NONE__'"})
        AND avg_rating >= 3.5
        ORDER BY director_boost DESC, avg_rating DESC
        LIMIT 30;
    """
    params = [fav_director or "", primary_genre] + (already_seen if already_seen else [])
    cursor.execute(query, params)
    pool = [dict(r) for r in cursor.fetchall()]
    conn.close()

    # Les films du réalisateur favori restent en tête, les autres sont mélangés
    fav_dir_movies = [m for m in pool if m.get("director_boost") == 1]
    other_movies   = [m for m in pool if m.get("director_boost") == 0]
    random.shuffle(other_movies)
    movies = (fav_dir_movies + other_movies)[:limit]
    return movies


# ── Phase 2 : Moteur IA (Pearson + K-Means) ──────────────────────────────────

def _recommend_ia(user_id, profile_type, age, limit=5) -> list:
    """
    Filtrage hybride :
      1. Réexécute K-Means pour mettre à jour les clusters
      2. Trouve les voisins du même cluster
      3. Calcule la corrélation de Pearson avec chaque voisin
      4. Agrège les films bien notés par les voisins les plus similaires
      5. Fallback sur le mode Expert si pas assez de résultats
    """
    # Mise à jour du clustering
    run_kmeans_clustering()

    conn = get_connection()
    cursor = conn.cursor()

    # Cluster de l'utilisateur courant
    cursor.execute("SELECT cluster_id FROM user_clusters WHERE user_id = ?;", (user_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return _recommend_expert(user_id, profile_type, age, limit)

    cluster_id = row["cluster_id"]

    # Voisins du même cluster (max 20)
    cursor.execute("""
        SELECT user_id FROM user_clusters
        WHERE cluster_id = ? AND user_id != ?
        LIMIT 20;
    """, (cluster_id, user_id))
    neighbors = [r["user_id"] for r in cursor.fetchall()]

    if not neighbors:
        conn.close()
        return _recommend_expert(user_id, profile_type, age, limit)

    # Corrélation de Pearson avec chaque voisin
    user_ratings = _get_rating_vector(user_id, conn)
    pearson_scores = []
    for nb_id in neighbors:
        nb_ratings = _get_rating_vector(nb_id, conn)
        score = _pearson(user_ratings, nb_ratings)
        if score > 0:
            pearson_scores.append((nb_id, score))

    pearson_scores.sort(key=lambda x: x[1], reverse=True)
    top_neighbors = [uid for uid, _ in pearson_scores[:5]]

    if not top_neighbors:
        conn.close()
        return _recommend_expert(user_id, profile_type, age, limit)

    # Films bien notés par les meilleurs voisins (≥ 4.0)
    already_seen = _get_excluded_movies(cursor, user_id)
    placeholders_nb = ",".join("?" * len(top_neighbors))
    placeholders_ex = ",".join("?" * len(already_seen)) if already_seen else "'__NONE__'"

    query = f"""
        SELECT r.movie as title, AVG(r.rating) as avg_rating, m.director, m.year, m.duration_min, m.genre
        FROM ratings r JOIN movies m ON r.movie = m.title
        WHERE r.user_id IN ({placeholders_nb})
        AND r.rating >= 4.0
        AND r.movie NOT IN ({placeholders_ex if already_seen else "'__NONE__'"})
        GROUP BY r.movie
        ORDER BY avg_rating DESC
        LIMIT ?;
    """
    params = top_neighbors + (already_seen if already_seen else []) + [limit]
    cursor.execute(query, params)
    movies = [dict(r) for r in cursor.fetchall()]
    conn.close()

    # Fallback si pas assez
    if len(movies) < limit:
        expert_movies = _recommend_expert(user_id, profile_type, age, limit - len(movies))
        existing_titles = {m["title"] for m in movies}
        for m in expert_movies:
            if m["title"] not in existing_titles:
                movies.append(m)

    return movies[:limit]


# ══════════════════════════════════════════════════════════════════════════════
# ALGORITHME K-MEANS (simplifié, basé sur les vecteurs de notes)
# ══════════════════════════════════════════════════════════════════════════════

def run_kmeans_clustering():
    """
    Regroupe tous les utilisateurs ayant des notes en K clusters.
    Chaque utilisateur est représenté par son vecteur de notes moyen par genre.
    Résultats persistés dans user_clusters.
    """
    conn = get_connection()
    cursor = conn.cursor()

    # Vecteur de chaque utilisateur : moyenne par genre
    cursor.execute("""
        SELECT r.user_id, m.genre, AVG(r.rating) as avg_r
        FROM ratings r JOIN movies m ON r.movie = m.title
        GROUP BY r.user_id, m.genre;
    """)
    rows = cursor.fetchall()

    if not rows:
        conn.close()
        return

    # Collecte tous les genres présents
    all_genres = sorted(set(r["genre"] for r in rows))
    user_vectors = defaultdict(lambda: [0.0] * len(all_genres))
    genre_idx = {g: i for i, g in enumerate(all_genres)}

    for r in rows:
        user_vectors[r["user_id"]][genre_idx[r["genre"]]] = r["avg_r"]

    users = list(user_vectors.keys())
    vectors = [user_vectors[u] for u in users]

    if len(users) < CLUSTER_COUNT:
        conn.close()
        return

    # Initialisation des centroïdes (K-Means++)
    centroids = [vectors[random.randint(0, len(vectors) - 1)]]
    while len(centroids) < CLUSTER_COUNT:
        dists = [min(_euclidean(v, c) for c in centroids) for v in vectors]
        total = sum(dists)
        if total == 0:
            break
        probs = [d / total for d in dists]
        cumulative = 0
        r_val = random.random()
        for i, p in enumerate(probs):
            cumulative += p
            if cumulative >= r_val:
                centroids.append(vectors[i])
                break

    # Itérations K-Means (max 20)
    assignments = [0] * len(users)
    for _ in range(20):
        new_assignments = [
            min(range(len(centroids)), key=lambda c: _euclidean(v, centroids[c]))
            for v in vectors
        ]
        if new_assignments == assignments:
            break
        assignments = new_assignments
        # Recalcul des centroïdes
        for c in range(len(centroids)):
            members = [vectors[i] for i, a in enumerate(assignments) if a == c]
            if members:
                centroids[c] = [sum(x) / len(members) for x in zip(*members)]

    # Persistance
    cursor.execute("DELETE FROM user_clusters;")
    import datetime
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for user, cluster in zip(users, assignments):
        cursor.execute(
            "INSERT OR REPLACE INTO user_clusters (user_id, cluster_id, updated_at) VALUES (?, ?, ?);",
            (user, cluster, now_str)
        )
    conn.commit()
    conn.close()


# ══════════════════════════════════════════════════════════════════════════════
# CORRÉLATION DE PEARSON
# ══════════════════════════════════════════════════════════════════════════════

def _get_rating_vector(user_id, conn) -> dict:
    """Retourne {film: note} pour un utilisateur."""
    cursor = conn.cursor()
    cursor.execute("SELECT movie, rating FROM ratings WHERE user_id = ?;", (user_id,))
    return {r["movie"]: r["rating"] for r in cursor.fetchall()}


def _pearson(v1: dict, v2: dict) -> float:
    """Corrélation de Pearson entre deux vecteurs de notes (dict film→note)."""
    common = set(v1.keys()) & set(v2.keys())
    n = len(common)
    if n < 2:
        return 0.0

    items = list(common)
    x = [v1[i] for i in items]
    y = [v2[i] for i in items]

    mx, my = sum(x) / n, sum(y) / n
    num = sum((a - mx) * (b - my) for a, b in zip(x, y))
    den = math.sqrt(sum((a - mx) ** 2 for a in x)) * math.sqrt(sum((b - my) ** 2 for b in y))
    return num / den if den != 0 else 0.0


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS PRIVÉS
# ══════════════════════════════════════════════════════════════════════════════

def _get_excluded_movies(cursor, user_id) -> list:
    """Retourne la liste des films déjà vus ou recommandés."""
    cursor.execute(
        "SELECT movie FROM ratings WHERE user_id = ? "
        "UNION SELECT movie FROM recommendations WHERE user_id = ? "
        "UNION SELECT movie FROM exploration_log WHERE user_id = ?;",
        (user_id, user_id, user_id)
    )
    return [r[0] for r in cursor.fetchall()]


def _log_exploration(user_id, titles: list):
    import datetime
    conn = get_connection()
    cursor = conn.cursor()
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for title in titles:
        cursor.execute(
            "INSERT INTO exploration_log (user_id, movie, shown_at) VALUES (?, ?, ?);",
            (user_id, title, now_str)
        )
    conn.commit()
    conn.close()


def _euclidean(v1: list, v2: list) -> float:
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(v1, v2)))


# ── Conservé pour compatibilité avec clean_data.py ────────────────────────────
def get_movies_by_genre(user_id, genre, limit=5):
    """Alias vers le moteur expert, pour rétro-compatibilité."""
    conn = get_connection()
    cursor = conn.cursor()
    query = """
        SELECT title, avg_rating, director, year, duration_min
        FROM movies
        WHERE genre = ?
        AND title NOT IN (SELECT movie FROM ratings WHERE user_id = ?)
        AND title NOT IN (SELECT movie FROM recommendations WHERE user_id = ?)
        ORDER BY avg_rating DESC
        LIMIT ?;
    """
    cursor.execute(query, (genre.lower(), user_id, user_id, limit))
    movies = cursor.fetchall()
    conn.close()
    return movies


# ══════════════════════════════════════════════════════════════════════════════
# FONCTIONS POUR CHARTS.PY
# ══════════════════════════════════════════════════════════════════════════════

def get_genre_distribution(user_id: str) -> dict:
    """
    Retourne {genre: count} pour les films notés par l'utilisateur.
    Utilisé par charts.py → graphique 01 (camembert genres).
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT m.genre, COUNT(*) as cnt
        FROM ratings r
        JOIN movies m ON r.movie = m.title
        WHERE r.user_id = ? AND m.genre IS NOT NULL
        GROUP BY m.genre
        ORDER BY cnt DESC;
    """, (user_id,))
    result = {row["genre"]: row["cnt"] for row in cursor.fetchall()}
    conn.close()
    return result


def get_ratings_over_time(user_id: str) -> list:
    """
    Retourne la liste des notes de l'utilisateur triées par timestamp.
    Chaque entrée : {"date": str, "avg_rating": float}
    Agrège par jour si plusieurs notes le même jour.
    Utilisé par charts.py → graphique 02 (timeline).
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT DATE(timestamp) as date, AVG(rating) as avg_rating, COUNT(*) as cnt
        FROM ratings
        WHERE user_id = ? AND timestamp IS NOT NULL
        GROUP BY DATE(timestamp)
        ORDER BY date ASC;
    """, (user_id,))
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows


def get_pearson_matrix_for_user(user_id: str, max_neighbors: int = 12) -> dict:
    """
    Calcule les scores de Pearson entre l'utilisateur et ses voisins de cluster.
    Retourne {
        "cluster_id": int,
        "scores": [{"name": str, "score": float, "common_movies": int}, ...]
    }
    Utilisé par charts.py → graphique 04.
    """
    conn = get_connection()
    cursor = conn.cursor()

    # Cluster de l'utilisateur
    cursor.execute(
        "SELECT cluster_id FROM user_clusters WHERE user_id = ?;", (user_id,)
    )
    row = cursor.fetchone()
    if not row:
        conn.close()
        return {}
    cluster_id = row["cluster_id"]

    # Voisins du même cluster
    cursor.execute("""
        SELECT uc.user_id, u.name
        FROM user_clusters uc
        JOIN users u ON uc.user_id = u.user_id
        WHERE uc.cluster_id = ? AND uc.user_id != ?
        LIMIT 50;
    """, (cluster_id, user_id))
    neighbors = [(r["user_id"], r["name"]) for r in cursor.fetchall()]

    # Notes du user cible
    cursor.execute(
        "SELECT movie, rating FROM ratings WHERE user_id = ?;", (user_id,)
    )
    target_ratings = {r["movie"]: r["rating"] for r in cursor.fetchall()}

    scores = []
    for nid, nname in neighbors:
        cursor.execute(
            "SELECT movie, rating FROM ratings WHERE user_id = ?;", (nid,)
        )
        neighbor_ratings = {r["movie"]: r["rating"] for r in cursor.fetchall()}

        common = list(set(target_ratings) & set(neighbor_ratings))
        if len(common) < 1:
            continue

        tv = [target_ratings[m] for m in common]
        nv = [neighbor_ratings[m] for m in common]

        # Pearson
        import math as _math
        n = len(tv)
        if n == 1:
            # Un seul film en commun → score = 1 si même note, sinon diff normalisée
            score = 1.0 - abs(tv[0] - nv[0]) / 4.0
        else:
            mean_t = sum(tv) / n
            mean_n = sum(nv) / n
            num = sum((t - mean_t) * (nv_i - mean_n) for t, nv_i in zip(tv, nv))
            den = (
                _math.sqrt(sum((t - mean_t) ** 2 for t in tv)) *
                _math.sqrt(sum((nv_i - mean_n) ** 2 for nv_i in nv))
            )
            score = num / den if den != 0 else 0.0

        scores.append({
            "name":          nname,
            "score":         round(score, 4),
            "common_movies": len(common)
        })

    conn.close()

    # Tri par score décroissant, on garde max_neighbors
    scores.sort(key=lambda x: x["score"], reverse=True)
    return {
        "cluster_id": cluster_id,
        "scores":     scores[:max_neighbors]
    }


def get_kmeans_global_viz() -> dict:
    """
    Agrège les données K-Means pour la visualisation globale.
    - Taille des clusters et note moyenne : depuis les ratings réels
    - Genre dominant par cluster        : depuis user_tags (genre déclaré),
      plus fiable que les films notés (pool ETL limité à 20 films)
    - Genre breakdown (stacked bar)     : depuis les ratings × genres films
    """
    conn = get_connection()
    cursor = conn.cursor()

    # Taille des clusters
    cursor.execute("""
        SELECT cluster_id, COUNT(*) as cnt
        FROM user_clusters
        GROUP BY cluster_id;
    """)
    cluster_sizes = {r["cluster_id"]: r["cnt"] for r in cursor.fetchall()}
    total_users = sum(cluster_sizes.values())

    if not cluster_sizes:
        conn.close()
        return {}

    # Note moyenne par cluster (toutes sources)
    cursor.execute("""
        SELECT uc.cluster_id,
               AVG(r.rating) as avg_rating,
               COUNT(r.rating) as cnt
        FROM user_clusters uc
        JOIN ratings r ON uc.user_id = r.user_id
        GROUP BY uc.cluster_id;
    """)
    avg_ratings = {}
    for r in cursor.fetchall():
        avg_ratings[r["cluster_id"]] = round(r["avg_rating"], 1)

    # Genre dominant par cluster : basé sur user_tags (genre déclaré à l'onboarding)
    # weight = 2.0 → genre primaire, 1.0 → secondaire — on pondère le décompte
    cursor.execute("""
        SELECT uc.cluster_id, ut.tag, SUM(ut.weight) as score
        FROM user_clusters uc
        JOIN user_tags ut ON uc.user_id = ut.user_id
        GROUP BY uc.cluster_id, ut.tag
        ORDER BY uc.cluster_id, score DESC;
    """)
    dominant_genres = {}
    seen_clusters = set()
    for r in cursor.fetchall():
        if r["cluster_id"] not in seen_clusters:
            dominant_genres[r["cluster_id"]] = r["tag"]
            seen_clusters.add(r["cluster_id"])

    # Fallback si user_tags vide : genre dominant par films notés
    if not dominant_genres:
        cursor.execute("""
            SELECT uc.cluster_id, m.genre, COUNT(*) as cnt
            FROM user_clusters uc
            JOIN ratings r ON uc.user_id = r.user_id
            JOIN movies m ON r.movie = m.title
            WHERE m.genre IS NOT NULL
            GROUP BY uc.cluster_id, m.genre
            ORDER BY uc.cluster_id, cnt DESC;
        """)
        seen = set()
        for r in cursor.fetchall():
            if r["cluster_id"] not in seen:
                dominant_genres[r["cluster_id"]] = r["genre"]
                seen.add(r["cluster_id"])

    # Genre breakdown (stacked bar) : % des films notés par genre dans chaque cluster
    cursor.execute("""
        SELECT uc.cluster_id, m.genre, COUNT(*) as cnt
        FROM user_clusters uc
        JOIN ratings r ON uc.user_id = r.user_id
        JOIN movies m ON r.movie = m.title
        WHERE m.genre IS NOT NULL
        GROUP BY uc.cluster_id, m.genre;
    """)
    cluster_genre_raw = {}
    for r in cursor.fetchall():
        cid = r["cluster_id"]
        if cid not in cluster_genre_raw:
            cluster_genre_raw[cid] = {}
        cluster_genre_raw[cid][r["genre"]] = cluster_genre_raw[cid].get(r["genre"], 0) + r["cnt"]

    genre_breakdown = {}
    for cid, genre_map in cluster_genre_raw.items():
        total = sum(genre_map.values())
        genre_breakdown[cid] = {
            g: round(cnt / total * 100, 1)
            for g, cnt in genre_map.items()
        }

    conn.close()

    return {
        "cluster_sizes":   cluster_sizes,
        "dominant_genres": dominant_genres,
        "avg_ratings":     avg_ratings,
        "genre_breakdown": genre_breakdown,
        "total_users":     total_users,
    }