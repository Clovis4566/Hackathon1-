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

Corrections v2 :
  • save_user_feedback : bloque la double notation d'un même film dans la même source
  • _recommend_expert  : diversification forcée — max 2 films par réalisateur
  • _recommend_ia      : diversification multi-genres via tags pondérés en fallback
  • get_genre_distribution / get_ratings_over_time : données pour les visualisations
"""
import sqlite3
import os
import math
import random
from collections import defaultdict

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "recommender.db")

MATURITY_THRESHOLD = 5
CLUSTER_COUNT      = 4

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

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS user_tags (
        user_id TEXT NOT NULL,
        tag     TEXT NOT NULL,
        weight  REAL DEFAULT 1.0,
        FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
    );""")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS user_clusters (
        user_id    TEXT PRIMARY KEY,
        cluster_id INTEGER NOT NULL,
        updated_at TEXT,
        FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
    );""")

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
# FONCTIONS UTILITAIRES DE BASE
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
        SELECT movie, rating, timestamp
        FROM ratings
        WHERE user_id = ?
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


def save_user_feedback(user_id, movie_title, rating_value):
    """
    Enregistre le vote d'un utilisateur sur un film recommandé.

    CORRECTION v2 : vérifie qu'il n'existe pas déjà une note
    'system_expert_feedback' pour ce film ET cet utilisateur.
    Si elle existe, met à jour la note au lieu d'insérer une nouvelle ligne.
    Cela empêche la barre de progression de gonfler artificiellement.
    """
    import datetime
    conn = get_connection()
    cursor = conn.cursor()
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        # Vérifie si une note feedback existe déjà pour ce film
        cursor.execute("""
            SELECT rating_id FROM ratings
            WHERE user_id = ? AND movie = ? AND source = 'system_expert_feedback'
            LIMIT 1;
        """, (user_id, movie_title))
        existing = cursor.fetchone()

        if existing:
            # Mise à jour de la note existante (ne compte pas dans la progression)
            cursor.execute("""
                UPDATE ratings SET rating = ?, timestamp = ?
                WHERE rating_id = ?;
            """, (float(rating_value), now_str, existing["rating_id"]))
            conn.commit()
            return "updated"   # Signal distinct pour main.py
        else:
            # Nouvelle note
            cursor.execute("""
                INSERT INTO ratings (user_id, movie, rating, timestamp, source, reason)
                VALUES (?, ?, ?, ?, 'system_expert_feedback', 'Évaluation de satisfaction post-recommandation');
            """, (user_id, movie_title, float(rating_value), now_str))
            conn.commit()
            return "inserted"
    except sqlite3.Error:
        return False
    finally:
        conn.close()


# ══════════════════════════════════════════════════════════════════════════════
# GESTION DES TAGS
# ══════════════════════════════════════════════════════════════════════════════

def save_user_tags(user_id, tags: list):
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
    conn = get_connection()
    cursor = conn.cursor()
    # Compte les films DISTINCTS notés (pas les doublons de notation)
    cursor.execute("""
        SELECT COUNT(DISTINCT movie) as cnt
        FROM ratings
        WHERE user_id = ? AND source = 'system_expert_feedback';
    """, (user_id,))
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
# DONNÉES POUR VISUALISATIONS
# ══════════════════════════════════════════════════════════════════════════════

def get_genre_distribution(user_id) -> dict:
    """
    Retourne {genre: nombre_de_films_notés} pour l'utilisateur.
    Utilisé pour le graphique camembert/barres de distribution des genres.
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT m.genre, COUNT(*) as cnt
        FROM ratings r
        JOIN movies m ON r.movie = m.title
        WHERE r.user_id = ?
        GROUP BY m.genre
        ORDER BY cnt DESC;
    """, (user_id,))
    result = {row["genre"]: row["cnt"] for row in cursor.fetchall()}
    conn.close()
    return result


def get_ratings_over_time(user_id) -> list:
    """
    Retourne une liste de (date, note_moyenne_du_jour) triée chronologiquement.
    Utilisé pour le graphique de tendance des notes dans le temps.
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT DATE(timestamp) as day, AVG(rating) as avg_r, COUNT(*) as cnt
        FROM ratings
        WHERE user_id = ? AND timestamp IS NOT NULL
        GROUP BY DATE(timestamp)
        ORDER BY day ASC;
    """, (user_id,))
    result = [{"day": row["day"], "avg_rating": round(row["avg_r"], 2), "count": row["cnt"]}
              for row in cursor.fetchall()]
    conn.close()
    return result


def get_pearson_matrix_for_user(user_id, max_neighbors=8) -> dict:
    """
    Calcule la corrélation de Pearson entre user_id et ses voisins de cluster.
    Retourne :
      {
        "user_name": str,
        "cluster_id": int,
        "scores": [ {"user_id", "name", "score", "common_movies"}, ... ],
        "user_vector": {film: note},
      }
    """
    conn = get_connection()
    cursor = conn.cursor()

    # Cluster de l'utilisateur
    cursor.execute("SELECT cluster_id FROM user_clusters WHERE user_id = ?;", (user_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return {}
    cluster_id = row["cluster_id"]

    # Nom de l'utilisateur
    cursor.execute("SELECT name FROM users WHERE user_id = ?;", (user_id,))
    name_row = cursor.fetchone()
    user_name = name_row["name"] if name_row else user_id

    # Voisins du même cluster
    cursor.execute("""
        SELECT uc.user_id, u.name
        FROM user_clusters uc
        JOIN users u ON uc.user_id = u.user_id
        WHERE uc.cluster_id = ? AND uc.user_id != ?
        LIMIT ?;
    """, (cluster_id, user_id, max_neighbors))
    neighbors = [(r["user_id"], r["name"]) for r in cursor.fetchall()]

    user_vec = _get_rating_vector(user_id, conn)
    scores = []
    for nb_id, nb_name in neighbors:
        nb_vec = _get_rating_vector(nb_id, conn)
        common = set(user_vec.keys()) & set(nb_vec.keys())
        score  = _pearson(user_vec, nb_vec)
        scores.append({
            "user_id":       nb_id,
            "name":          nb_name,
            "score":         round(score, 3),
            "common_movies": len(common),
        })

    scores.sort(key=lambda x: x["score"], reverse=True)
    conn.close()
    return {
        "user_name":   user_name,
        "cluster_id":  cluster_id,
        "scores":      scores,
        "user_vector": user_vec,
    }


def get_pearson_top_pairs_global(limit=12) -> list:
    """
    Calcule les paires d'utilisateurs les plus similaires sur TOUTE la base.
    Retourne une liste triée de {"user_a", "user_b", "score", "common_movies"}.
    Limité aux utilisateurs ayant au moins 3 films notés pour éviter les corrélations vides.
    """
    conn = get_connection()
    cursor = conn.cursor()

    # Utilisateurs avec au moins 3 films notés
    cursor.execute("""
        SELECT user_id FROM ratings
        GROUP BY user_id HAVING COUNT(DISTINCT movie) >= 3
        LIMIT 60;
    """)
    eligible = [r["user_id"] for r in cursor.fetchall()]

    # Noms
    placeholders = ",".join("?" * len(eligible)) if eligible else "'__'"
    cursor.execute(f"SELECT user_id, name FROM users WHERE user_id IN ({placeholders});", eligible)
    names = {r["user_id"]: r["name"] for r in cursor.fetchall()}

    # Vecteurs
    vectors = {uid: _get_rating_vector(uid, conn) for uid in eligible}

    pairs = []
    for i in range(len(eligible)):
        for j in range(i + 1, len(eligible)):
            uid_a, uid_b = eligible[i], eligible[j]
            common = set(vectors[uid_a].keys()) & set(vectors[uid_b].keys())
            if len(common) < 2:
                continue
            score = _pearson(vectors[uid_a], vectors[uid_b])
            pairs.append({
                "user_a":        names.get(uid_a, uid_a),
                "user_b":        names.get(uid_b, uid_b),
                "score":         round(score, 3),
                "common_movies": len(common),
            })

    conn.close()
    pairs.sort(key=lambda x: x["score"], reverse=True)
    return pairs[:limit]


def get_kmeans_viz_data(user_id) -> dict:
    """
    Données pour la visualisation K-Means de l'utilisateur :
      - cluster_id de l'utilisateur
      - genre dominant de son cluster
      - liste des voisins avec leur genre dominant
      - taille de chaque cluster
    """
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT cluster_id FROM user_clusters WHERE user_id = ?;", (user_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return {}
    user_cluster = row["cluster_id"]

    # Taille de chaque cluster
    cursor.execute("""
        SELECT cluster_id, COUNT(*) as cnt
        FROM user_clusters GROUP BY cluster_id;
    """)
    cluster_sizes = {r["cluster_id"]: r["cnt"] for r in cursor.fetchall()}

    # Genre dominant par cluster (genre le plus noté en moyenne)
    cursor.execute("""
        SELECT uc.cluster_id, m.genre, COUNT(*) as cnt
        FROM user_clusters uc
        JOIN ratings r ON uc.user_id = r.user_id
        JOIN movies  m ON r.movie    = m.title
        GROUP BY uc.cluster_id, m.genre;
    """)
    cluster_genres = defaultdict(lambda: defaultdict(int))
    for r in cursor.fetchall():
        cluster_genres[r["cluster_id"]][r["genre"]] += r["cnt"]

    dominant_genres = {}
    for cid, genres in cluster_genres.items():
        dominant_genres[cid] = max(genres, key=genres.get) if genres else "?"

    # Voisins du même cluster (max 10)
    cursor.execute("""
        SELECT uc.user_id, u.name, u.profile_type
        FROM user_clusters uc JOIN users u ON uc.user_id = u.user_id
        WHERE uc.cluster_id = ? AND uc.user_id != ?
        LIMIT 10;
    """, (user_cluster, user_id))
    neighbors = [{"user_id": r["user_id"], "name": r["name"], "genre": r["profile_type"]}
                 for r in cursor.fetchall()]

    cursor.execute("SELECT name FROM users WHERE user_id = ?;", (user_id,))
    nm = cursor.fetchone()
    conn.close()

    return {
        "user_name":      nm["name"] if nm else user_id,
        "user_cluster":   user_cluster,
        "cluster_sizes":  cluster_sizes,
        "dominant_genres": dominant_genres,
        "neighbors":      neighbors,
        "total_clusters": len(cluster_sizes),
    }


def get_kmeans_global_viz() -> dict:
    """
    Vue globale K-Means sur toute la base :
      - répartition des utilisateurs par cluster
      - genre dominant et note moyenne par cluster
      - nombre total d'utilisateurs clusterisés
    """
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT cluster_id, COUNT(*) as cnt
        FROM user_clusters GROUP BY cluster_id ORDER BY cluster_id;
    """)
    cluster_sizes = {r["cluster_id"]: r["cnt"] for r in cursor.fetchall()}

    # Note moyenne par cluster
    cursor.execute("""
        SELECT uc.cluster_id, AVG(r.rating) as avg_r
        FROM user_clusters uc JOIN ratings r ON uc.user_id = r.user_id
        GROUP BY uc.cluster_id;
    """)
    cluster_avg_rating = {r["cluster_id"]: round(r["avg_r"], 2) for r in cursor.fetchall()}

    # Genre dominant par cluster
    cursor.execute("""
        SELECT uc.cluster_id, m.genre, COUNT(*) as cnt
        FROM user_clusters uc
        JOIN ratings r ON uc.user_id = r.user_id
        JOIN movies  m ON r.movie    = m.title
        GROUP BY uc.cluster_id, m.genre;
    """)
    cluster_genres = defaultdict(lambda: defaultdict(int))
    for r in cursor.fetchall():
        cluster_genres[r["cluster_id"]][r["genre"]] += r["cnt"]

    dominant_genres = {}
    genre_breakdown = {}
    for cid, genres in cluster_genres.items():
        dominant_genres[cid] = max(genres, key=genres.get) if genres else "?"
        total = sum(genres.values())
        genre_breakdown[cid] = {g: round(c / total * 100, 1) for g, c in
                                 sorted(genres.items(), key=lambda x: x[1], reverse=True)[:4]}

    conn.close()
    return {
        "cluster_sizes":    cluster_sizes,
        "dominant_genres":  dominant_genres,
        "avg_ratings":      cluster_avg_rating,
        "genre_breakdown":  genre_breakdown,
        "total_users":      sum(cluster_sizes.values()),
    }


# ══════════════════════════════════════════════════════════════════════════════
# MOTEUR DE RECOMMANDATION — SÉLECTION AUTOMATIQUE
# ══════════════════════════════════════════════════════════════════════════════

def get_recommendations(user_id, profile_type, age, limit=5) -> tuple:
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
    1 film par genre déclaré, puis complète avec d'autres genres si nécessaire.
    Diversification par réalisateur : max 1 film par réalisateur.
    """
    conn = get_connection()
    cursor = conn.cursor()

    tags = get_user_tags(user_id)
    if tags:
        genres = [t[0] for t in tags]
    else:
        genres = [profile_type]
        all_genres = get_all_unique_genres()
        extras = [g for g in all_genres if g != profile_type]
        random.shuffle(extras)
        genres += extras[:2]

    already_seen = _get_excluded_movies(cursor, user_id)
    result = []
    seen_directors = set()

    for genre in genres:
        if len(result) >= limit:
            break
        rows = _fetch_diverse_movies(cursor, genre, already_seen, seen_directors, needed=2)
        result += rows
        seen_directors.update(r["director"] for r in rows if r.get("director"))

    # Complète si moins de `limit` films
    if len(result) < limit:
        all_genres = get_all_unique_genres()
        for genre in all_genres:
            if genre in genres or len(result) >= limit:
                continue
            rows = _fetch_diverse_movies(cursor, genre, already_seen, seen_directors, needed=1)
            result += rows
            seen_directors.update(r["director"] for r in rows if r.get("director"))

    conn.close()
    _log_exploration(user_id, [m["title"] for m in result[:limit]])
    return result[:limit]


# ── Phase 1b : Système Expert ─────────────────────────────────────────────────

def _recommend_expert(user_id, profile_type, age, limit=5) -> list:
    """
    Filtrage par contenu avec diversification obligatoire :
    - Pioche dans chaque tag (genre primaire en priorité, secondaires en appoint)
    - Max 2 films par réalisateur pour éviter la monotonie
    - Biais réalisateur : le réalisateur favori est proposé en premier, mais limité à 2 films
    """
    conn = get_connection()
    cursor = conn.cursor()

    tags = get_user_tags(user_id)
    if tags:
        genres = [t[0] for t in tags]
    else:
        genres = [profile_type.lower()]

    # Réalisateur favori
    cursor.execute("""
        SELECT m.director, AVG(r.rating) as avg_r
        FROM ratings r JOIN movies m ON r.movie = m.title
        WHERE r.user_id = ? AND r.rating >= 4.0
        GROUP BY m.director ORDER BY avg_r DESC LIMIT 1;
    """, (user_id,))
    fav_row = cursor.fetchone()
    fav_director = fav_row["director"] if fav_row else None

    already_seen = _get_excluded_movies(cursor, user_id)
    result = []
    director_count = defaultdict(int)
    MAX_PER_DIRECTOR = 2

    # Genre primaire en priorité
    primary = genres[0]
    primary_rows = _fetch_diverse_movies(
        cursor, primary, already_seen, set(),
        needed=min(3, limit),
        preferred_director=fav_director,
        max_per_director=MAX_PER_DIRECTOR
    )
    for r in primary_rows:
        director_count[r.get("director", "")] += 1
        result.append(r)

    # Genres secondaires en appoint
    for genre in genres[1:]:
        if len(result) >= limit:
            break
        rows = _fetch_diverse_movies(
            cursor, genre, already_seen,
            {d for d, c in director_count.items() if c >= MAX_PER_DIRECTOR},
            needed=limit - len(result),
            max_per_director=MAX_PER_DIRECTOR
        )
        for r in rows:
            director_count[r.get("director", "")] += 1
            result.append(r)
            if len(result) >= limit:
                break

    # Fallback : autres genres si encore insuffisant
    if len(result) < limit:
        all_genres = get_all_unique_genres()
        for genre in all_genres:
            if genre in genres or len(result) >= limit:
                continue
            rows = _fetch_diverse_movies(cursor, genre, already_seen, set(), needed=1)
            result += rows

    conn.close()
    return result[:limit]


# ── Phase 2 : Moteur IA (Pearson + K-Means) ──────────────────────────────────

def _recommend_ia(user_id, profile_type, age, limit=5) -> list:
    """
    Filtrage collaboratif :
      1. K-Means pour trouver les voisins du même cluster
      2. Pearson pour sélectionner les 5 voisins les plus similaires
      3. Films bien notés par ces voisins, diversifiés par genre ET réalisateur
      4. Fallback Expert si résultats insuffisants
    """
    run_kmeans_clustering()

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT cluster_id FROM user_clusters WHERE user_id = ?;", (user_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return _recommend_expert(user_id, profile_type, age, limit)

    cluster_id = row["cluster_id"]

    cursor.execute("""
        SELECT user_id FROM user_clusters
        WHERE cluster_id = ? AND user_id != ?
        LIMIT 20;
    """, (cluster_id, user_id))
    neighbors = [r["user_id"] for r in cursor.fetchall()]

    if not neighbors:
        conn.close()
        return _recommend_expert(user_id, profile_type, age, limit)

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

    already_seen = _get_excluded_movies(cursor, user_id)
    placeholders_nb = ",".join("?" * len(top_neighbors))
    placeholders_ex = ",".join("?" * len(already_seen)) if already_seen else "'__NONE__'"

    # Films bien notés par les voisins, diversifiés : on prend jusqu'à limit*3
    # puis on filtre pour max 2 par réalisateur et max 2 par genre
    query = f"""
        SELECT r.movie as title, AVG(r.rating) as avg_rating, m.director, m.year,
               m.duration_min, m.genre
        FROM ratings r JOIN movies m ON r.movie = m.title
        WHERE r.user_id IN ({placeholders_nb})
        AND r.rating >= 4.0
        AND r.movie NOT IN ({placeholders_ex if already_seen else "'__NONE__'"})
        GROUP BY r.movie
        ORDER BY avg_rating DESC
        LIMIT ?;
    """
    params = top_neighbors + (already_seen if already_seen else []) + [limit * 3]
    cursor.execute(query, params)
    candidates = [dict(r) for r in cursor.fetchall()]
    conn.close()

    # Diversification : max 2 par réalisateur, max 2 par genre
    movies = _diversify(candidates, max_per_director=2, max_per_genre=2, limit=limit)

    # Fallback si pas assez
    if len(movies) < limit:
        expert_movies = _recommend_expert(user_id, profile_type, age, limit - len(movies))
        existing_titles = {m["title"] for m in movies}
        for m in expert_movies:
            if m["title"] not in existing_titles:
                movies.append(m)

    return movies[:limit]


# ══════════════════════════════════════════════════════════════════════════════
# ALGORITHME K-MEANS
# ══════════════════════════════════════════════════════════════════════════════

def run_kmeans_clustering():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT r.user_id, m.genre, AVG(r.rating) as avg_r
        FROM ratings r JOIN movies m ON r.movie = m.title
        GROUP BY r.user_id, m.genre;
    """)
    rows = cursor.fetchall()

    if not rows:
        conn.close()
        return

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

    # K-Means++
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

    assignments = [0] * len(users)
    for _ in range(20):
        new_assignments = [
            min(range(len(centroids)), key=lambda c: _euclidean(v, centroids[c]))
            for v in vectors
        ]
        if new_assignments == assignments:
            break
        assignments = new_assignments
        for c in range(len(centroids)):
            members = [vectors[i] for i, a in enumerate(assignments) if a == c]
            if members:
                centroids[c] = [sum(x) / len(members) for x in zip(*members)]

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
    cursor = conn.cursor()
    cursor.execute("SELECT movie, rating FROM ratings WHERE user_id = ?;", (user_id,))
    return {r["movie"]: r["rating"] for r in cursor.fetchall()}


def _pearson(v1: dict, v2: dict) -> float:
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
    cursor.execute(
        "SELECT movie FROM ratings WHERE user_id = ? "
        "UNION SELECT movie FROM recommendations WHERE user_id = ? "
        "UNION SELECT movie FROM exploration_log WHERE user_id = ?;",
        (user_id, user_id, user_id)
    )
    return [r[0] for r in cursor.fetchall()]


def _fetch_diverse_movies(cursor, genre, already_seen, blocked_directors,
                          needed=1, preferred_director=None, max_per_director=2) -> list:
    """
    Récupère jusqu'à `needed` films d'un genre donné en respectant :
    - exclusion des films déjà vus
    - exclusion des réalisateurs bloqués (quota atteint)
    - préférence pour preferred_director (en tête de liste)
    """
    placeholders_ex = ",".join("?" * len(already_seen)) if already_seen else "'__NONE__'"
    placeholders_bd = ",".join("?" * len(blocked_directors)) if blocked_directors else "'__NONE__'"

    preferred_director_val = preferred_director or ""

    query = f"""
        SELECT title, avg_rating, director, year, duration_min, genre,
               CASE WHEN director = ? THEN 1 ELSE 0 END as pref_boost
        FROM movies
        WHERE genre = ?
        AND title NOT IN ({placeholders_ex if already_seen else "'__NONE__'"})
        AND (director NOT IN ({placeholders_bd if blocked_directors else "'__NONE__'"}))
        ORDER BY pref_boost DESC, avg_rating DESC
        LIMIT ?;
    """
    params = (
        [preferred_director_val, genre]
        + (already_seen if already_seen else [])
        + (list(blocked_directors) if blocked_directors else [])
        + [needed * max_per_director]   # On récupère plus pour filtrer ensuite
    )
    cursor.execute(query, params)
    rows = [dict(r) for r in cursor.fetchall()]

    # Diversification : max `max_per_director` par réalisateur dans ce lot
    result = []
    local_director_count = defaultdict(int)
    for row in rows:
        d = row.get("director", "")
        if local_director_count[d] < max_per_director:
            result.append(row)
            local_director_count[d] += 1
        if len(result) >= needed:
            break
    return result


def _diversify(candidates: list, max_per_director=2, max_per_genre=2, limit=5) -> list:
    """Filtre une liste de candidats pour garantir la diversité réalisateur + genre."""
    result = []
    director_count = defaultdict(int)
    genre_count = defaultdict(int)

    for m in candidates:
        d = m.get("director", "")
        g = m.get("genre", "")
        if director_count[d] < max_per_director and genre_count[g] < max_per_genre:
            result.append(m)
            director_count[d] += 1
            genre_count[g] += 1
        if len(result) >= limit:
            break

    # Deuxième passe sans contrainte genre si pas assez
    if len(result) < limit:
        existing = {m["title"] for m in result}
        for m in candidates:
            if m["title"] in existing:
                continue
            d = m.get("director", "")
            if director_count[d] < max_per_director:
                result.append(m)
                director_count[d] += 1
            if len(result) >= limit:
                break

    return result[:limit]


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


# ── Rétro-compatibilité clean_data.py ─────────────────────────────────────────
def get_movies_by_genre(user_id, genre, limit=5):
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