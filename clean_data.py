"""
clean_data.py
─────────────
Pipeline ETL 100% Pandas : Vectorisé, ultra-léger et pédagogique pour l'exposé.
Génère et nettoie 500+ lignes de données cinématographiques réalistes et variées.

Évolutions vs version initiale :
  • Après l'import des données, un premier clustering K-Means est exécuté
    pour initialiser la table user_clusters dès le départ.
  • Les nouveaux champs (user_tags) sont pré-remplis pour les utilisateurs
    générés automatiquement, afin de valider le moteur IA immédiatement.
  • La logique ETL et les affichages didactiques sont 100% conservés.
"""
import os
import pandas as pd
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import database

DATA_DIR = os.path.dirname(os.path.abspath(__file__))

GENRE_MAP = {
    "sci-fi": "sci-fi", "scifi": "sci-fi", "sci fi": "sci-fi", "science fiction": "sci-fi",
    "action": "action", "thriller": "thriller", "thriler": "thriller",
    "drama": "drama", "drame": "drama", "horror": "horror", "horreur": "horror",
    "comedy": "comedy", "comedie": "comedy", "romance": "romance", "animation": "animation"
}


def generate_large_dirty_csv_files():
    """Génère de gros volumes de données réalistes mais sales via des opérations vectorisées."""
    os.makedirs(DATA_DIR, exist_ok=True)

    raw_data_movies = {
        "title_base": [
            "Inception", "Interstellar", "The Matrix", "Avatar", "Gladiator", "The Dark Knight",
            "Toy Story", "The Conjuring", "La La Land", "The Hangover", "Seven", "Spirited Away",
            "Pulp Fiction", "Titanic", "Superbad", "Get Out", "Blade Runner 2049", "Parasite"
        ],
        "genre": [
            "science fiction", "sci-fi", "action", "thriler", "drama", "action",
            "animation", "horror", "romance", "comedy", "thriller", "animation",
            "drama", "romance", "comedy", "horreur", "sci fi", "thriller"
        ],
        "duration_min": ["148", "-169", "136", "9999", "155", "152", "81", "112", "128", "100", "127", "125", "154", "194", "-113", "104", "164", "132"],
        "avg_rating":   ["4.8", "4.7.0.0", "9.5", "4.1", "NaN", "4.9", "4.3", "3.9", "4.2", "3.8", "4.6", "4.8", "4.5", "4.0", "3.7", "4.1", "4.4", "4.6"],
        "year":         ["2010", None, "1999", "2009", "2000", "2008", "1995", "2013", "2016", "2009", "1995", "2001", "1994", "1997", "2007", "2017", "2017", "2019"],
        "director": [
            "Christopher Nolan", "Christopher Nolan", "Lana Wachowski", "James Cameron", "Ridley Scott", "Christopher Nolan",
            "John Lasseter", "James Wan", "Damien Chazelle", "Todd Phillips", "David Fincher", "Hayao Miyazaki",
            "Quentin Tarantino", "James Cameron", "Greg Mottola", "Jordan Peele", "Denis Villeneuve", "Bong Joon Ho"
        ]
    }

    df_src_m = pd.DataFrame(raw_data_movies)

    suffixes = [
        "Original", "Reloaded", "Evolution", "Legacy", "Reborn", "The Sequel",
        "Chapter II", "Trilogy", "Saga", "Origins", "Uncut", "Remastered",
        "Part I", "Part II", "Part III", "The Return", "Forever", "The Next Generation",
        "Chronicles", "Anniversary Edition", "Director's Cut", "Final Cut", "Gold Edition", "Redux", "Beyond"
    ]

    df_list = []
    for suff in suffixes:
        df_temp = df_src_m.copy()
        df_temp["title"] = df_temp["title_base"] + " " + suff
        df_list.append(df_temp)

    df_movies = pd.concat(df_list, ignore_index=True)
    df_movies["movie_id"]    = [f"M{i:03d}" for i in range(1, len(df_movies) + 1)]
    df_movies["pace"]        = "fast"
    df_movies.loc[df_movies.index % 3 == 0, "pace"] = "LENT"
    df_movies["description"] = "Synopsis de test généré par le pipeline de données Pandas."

    df_movies.loc[df_movies.index % 80 == 0, :] = None
    df_movies = pd.concat([df_movies, df_movies.head(5)], ignore_index=True)
    df_movies.to_csv(os.path.join(DATA_DIR, "raw_movies.csv"), index=False)

    # ── Utilisateurs ──────────────────────────────────────────────────────────
    df_src_u = pd.DataFrame({
        "name_base":    ["Brou", "Alice", "Bob", "Charlie", "Thomas", "Georges", "Julie", "Sarah", "Marc", "Sophie"],
        "age":          ["22", "-5", "35", None, "18", "23", "31", "-12", "45", "62"],
        "profile_type": ["mixed", "comedy", "action", "sci-fi", "horror", "thriller", "romance", "animation", "drama", "mixed"]
    })
    df_users = pd.concat([df_src_u] * 55, ignore_index=True)
    df_users["user_id"] = [f"U{i:03d}" for i in range(1, len(df_users) + 1)]
    df_users["name"]    = df_users["name_base"] + "_" + df_users.index.astype(str)
    df_users.to_csv(os.path.join(DATA_DIR, "raw_users.csv"), index=False)

    # ── Ratings réalistes selon le profil utilisateur ────────────────────────
    #
    # Logique : chaque utilisateur note des films cohérents avec son profil.
    #   - Films du genre favori    → notes hautes  (3.5 – 5.0)
    #   - Films de genres neutres  → notes moyennes (2.5 – 3.9)
    #   - Films de genres opposés  → notes basses   (1.0 – 2.9)
    #
    # Chaque user reçoit entre 3 et 7 notes sur des films différents,
    # répartis sur plusieurs dates pour donner une vraie timeline.

    import random as _rnd

    # Genre opposé par profil (ex: fan d'action → romance est l'opposé)
    OPPOSITES = {
        "action":    ["romance", "animation"],
        "comedy":    ["horror",  "thriller"],
        "sci-fi":    ["romance", "comedy"],
        "horror":    ["romance", "comedy"],
        "thriller":  ["comedy",  "animation"],
        "romance":   ["horror",  "action"],
        "animation": ["horror",  "thriller"],
        "drama":     ["horror",  "sci-fi"],
        "mixed":     [],
    }

    # Pool de films par genre (titres présents dans raw_movies)
    GENRE_POOLS = {
        "sci-fi":    ["Inception Original", "Interstellar Original", "Blade Runner 2049 Original",
                      "The Matrix Original"],
        "action":    ["The Dark Knight Original", "Gladiator Original", "Avatar Original",
                      "The Matrix Original"],
        "thriller":  ["Seven Original", "Avatar Original", "Parasite Original"],
        "drama":     ["Gladiator Original", "Pulp Fiction Original", "Parasite Original",
                      "Titanic Original"],
        "comedy":    ["The Hangover Original", "Superbad Original"],
        "horror":    ["The Conjuring Original", "Get Out Original"],
        "romance":   ["La La Land Original", "Titanic Original"],
        "animation": ["Toy Story Original", "Spirited Away Original"],
    }
    # Fallback générique si un titre manque dans la base nettoyée
    ALL_MOVIE_POOL = [
        "Inception Original", "Gladiator Legacy", "Avatar Part I", "The Matrix Reloaded",
        "The Hangover Original", "Toy Story Evolution", "Seven Reborn", "La La Land Saga",
        "Interstellar Original", "The Dark Knight Original", "Pulp Fiction Original",
        "Titanic Original", "The Conjuring Original", "Parasite Original",
        "Get Out Original", "Spirited Away Original", "Blade Runner 2049 Original",
        "Superbad Original"
    ]

    rating_rows = []
    dates = [
        "2026-01-15 10:00:00", "2026-02-03 18:30:00", "2026-02-20 21:00:00",
        "2026-03-08 14:15:00", "2026-03-25 20:00:00", "2026-04-10 16:45:00",
        "2026-05-01 19:30:00", "2026-05-18 22:00:00", "2026-06-01 14:22:00",
    ]

    df_u_ref = pd.read_csv(os.path.join(DATA_DIR, "raw_users.csv")) if os.path.exists(
        os.path.join(DATA_DIR, "raw_users.csv")) else pd.DataFrame({"user_id": [f"U{i:03d}" for i in range(1,551)], "profile_type": ["mixed"]*550})

    profile_map = dict(zip(df_u_ref["user_id"], df_u_ref["profile_type"].fillna("mixed")))

    for uid, profile in profile_map.items():
        profile = str(profile).lower().strip()
        if profile not in OPPOSITES:
            profile = "mixed"

        opposites = OPPOSITES.get(profile, [])
        n_ratings = _rnd.randint(3, 7)
        used_movies = set()

        # 60% films du genre favori, 25% neutres, 15% opposés
        for k in range(n_ratings):
            roll = _rnd.random()
            if roll < 0.60 and profile != "mixed":
                pool = GENRE_POOLS.get(profile, ALL_MOVIE_POOL)
                rating = round(_rnd.uniform(3.5, 5.0), 1)
            elif roll < 0.85 or profile == "mixed":
                pool = ALL_MOVIE_POOL
                rating = round(_rnd.uniform(2.5, 3.9), 1)
            else:
                opp = _rnd.choice(opposites) if opposites else None
                pool = GENRE_POOLS.get(opp, ALL_MOVIE_POOL) if opp else ALL_MOVIE_POOL
                rating = round(_rnd.uniform(1.0, 2.9), 1)

            # Choisir un film non déjà noté par cet user
            candidates = [m for m in pool if m not in used_movies]
            if not candidates:
                candidates = [m for m in ALL_MOVIE_POOL if m not in used_movies]
            if not candidates:
                break

            movie = _rnd.choice(candidates)
            used_movies.add(movie)
            date = dates[k % len(dates)]
            rating_rows.append({
                "user_id":     uid,
                "movie_title": movie,
                "rating":      str(rating),
                "timestamp":   date,
            })

    df_ratings = pd.DataFrame(rating_rows)
    # Injection des erreurs volontaires pour démontrer le nettoyage ETL
    n = len(df_ratings)
    err_idx = df_ratings.sample(frac=0.05, random_state=42).index
    df_ratings.loc[err_idx, "rating"] = "15.0"
    null_idx = df_ratings.sample(frac=0.04, random_state=7).index
    df_ratings.loc[null_idx, "timestamp"] = None
    df_ratings.to_csv(os.path.join(DATA_DIR, "raw_ratings.csv"), index=False)


def present_step(step_num, title, df_raw, df_clean, explanations):
    """Affichage didactique de l'état des transformations."""
    print("\n" + "═"*85)
    print(f" 🎬 ÉTAPE {step_num} : {title}")
    print("═"*85)
    print("\nEXTRAIT DES DONNÉES BRUTES SÉLECTIONNÉES (AVANT) :")
    print("-" * 85)
    print(df_raw.dropna().head(5).to_string(index=False))
    print(f"Nombre total de lignes au départ : {len(df_raw)}")

    print("\n⚙️ ACTIONS DE NETTOYAGE APPLIQUÉES (100% PANDAS) :")
    for exp in explanations:
        print(f"  ➔ {exp}")

    input("\n➡ Appuyez sur ENTRÉE pour exécuter le code Pandas et voir le résultat...")

    print("\n✨ EXTRAIT DES DONNÉES NETTOYÉES ET NORMALISÉES (APRÈS) :")
    print("-" * 85)
    print(df_clean.head(5).to_string(index=False))
    print(f"Nombre total de lignes conservées : {len(df_clean)}")
    print("═"*85)


def reset_database_tables(conn):
    cursor = conn.cursor()
    cursor.execute("DELETE FROM ratings;")
    cursor.execute("DELETE FROM users;")
    cursor.execute("DELETE FROM movies;")
    cursor.execute("DELETE FROM user_tags;")
    cursor.execute("DELETE FROM user_clusters;")
    cursor.execute("DELETE FROM exploration_log;")
    conn.commit()


def run_full_etl_pipeline():
    generate_large_dirty_csv_files()
    database.create_tables()
    conn = database.get_connection()
    reset_database_tables(conn)

    # ──────────────────────────────────────────────────────────────────────────
    # ÉTAPE 1 : MOVIES
    # ──────────────────────────────────────────────────────────────────────────
    df_raw_m = pd.read_csv(os.path.join(DATA_DIR, "raw_movies.csv"))

    df_m = df_raw_m.dropna(subset=["movie_id", "title"]).copy()
    df_m["duration_min"] = pd.to_numeric(df_m["duration_min"], errors="coerce").abs().fillna(120).astype(int)
    df_m.loc[df_m["duration_min"] > 300, "duration_min"] = 120
    df_m["year"]  = pd.to_numeric(df_m["year"], errors="coerce").fillna(2026).astype(int)
    df_m["genre"] = df_m["genre"].astype(str).str.lower().str.strip().map(GENRE_MAP).fillna("sci-fi")

    df_m["avg_rating"] = df_m["avg_rating"].astype(str).str.extract(r"(\d+\.\d+|\d+)")[0].astype(float)
    df_m["avg_rating"] = df_m["avg_rating"].where(df_m["avg_rating"] <= 5.0, 4.2).fillna(4.2)

    df_m["pace"] = df_m["pace"].str.lower().replace({"lent": "slow", "rapide": "fast"}).fillna("slow")
    df_m = df_m.drop_duplicates(subset=["title"], keep="first")
    df_m = df_m[["movie_id", "title", "genre", "duration_min", "avg_rating", "year", "pace", "director", "description"]]

    present_step(
        "1", "NETTOYAGE DU CATALOGUE DES FILMS (MOVIES)", df_raw_m, df_m,
        [
            ".dropna(subset=[...]) : Élimination des lignes complètement vides ou sans ID.",
            ".to_numeric(..., errors='coerce').abs() : Conversion des durées et suppression des valeurs négatives.",
            ".str.extract(r'regex') : Extraction intelligente de la note (règle le bug des points multiples).",
            ".drop_duplicates(subset=['title']) : Déduplication stricte sur le titre unique du film."
        ]
    )
    df_m.to_csv(os.path.join(DATA_DIR, "clean_movies.csv"), index=False)
    df_m.to_sql("movies", conn, if_exists="append", index=False)

    # ──────────────────────────────────────────────────────────────────────────
    # ÉTAPE 2 : USERS
    # ──────────────────────────────────────────────────────────────────────────
    df_raw_u = pd.read_csv(os.path.join(DATA_DIR, "raw_users.csv"))

    df_u = df_raw_u.dropna(subset=["user_id", "name"]).copy()
    df_u = df_u.drop_duplicates(subset=["user_id"], keep="first")
    df_u["age"] = pd.to_numeric(df_u["age"], errors="coerce").clip(15, 99).fillna(25).astype(int)

    df_u["session_code"]    = df_u["name"].str.upper() + "-59A4C"
    df_u["secret_question"] = "Quel est ton film préféré ?"
    df_u["secret_answer"]   = "cinéma"
    df_u = df_u[["user_id", "name", "age", "profile_type", "session_code", "secret_question", "secret_answer"]]

    present_step(
        "2", "NETTOYAGE ET SÉCURISATION DES UTILISATEURS (USERS)", df_raw_u, df_u,
        [
            ".drop_duplicates('user_id') : Suppression instantanée des conflits de clés primaires.",
            ".clip(15, 99) : Redressement automatique des âges négatifs ou aberrants.",
            "df['name'].str.upper() : Concaténation vectorielle pour générer le jeton de session."
        ]
    )
    df_u.to_csv(os.path.join(DATA_DIR, "clean_users.csv"), index=False)
    df_u.to_sql("users", conn, if_exists="append", index=False)

    # ── Génération des user_tags pour les utilisateurs ETL ───────────────────
    print("\n⚙️  Génération des tags multi-genres pour les utilisateurs générés...")
    conn.close()
    for _, row in df_u.iterrows():
        profile = row["profile_type"] if isinstance(row["profile_type"], str) else "action"
        database.save_user_tags(row["user_id"], [profile])
    conn = database.get_connection()
    print(f"    Tags enregistrés pour {len(df_u)} utilisateurs.")

    # ──────────────────────────────────────────────────────────────────────────
    # ÉTAPE 3 : RATINGS
    # ──────────────────────────────────────────────────────────────────────────
    df_raw_r = pd.read_csv(os.path.join(DATA_DIR, "raw_ratings.csv"))

    df_r = df_raw_r.dropna(subset=["user_id", "movie_title"]).copy()
    df_r = df_r.rename(columns={"movie_title": "movie"})
    df_r["rating"]    = df_r["rating"].astype(str).str.extract(r"(\d+\.\d+|\d+)")[0].astype(float)
    df_r["rating"]    = df_r["rating"].clip(1.0, 5.0).fillna(3.5)
    df_r["timestamp"] = df_r["timestamp"].fillna("2026-06-01 00:00:00")
    df_r["source"]    = "history"
    df_r["reason"]    = "Donnée importée via pipeline ETL vectorisé"

    df_r = df_r[df_r["user_id"].isin(df_u["user_id"]) & df_r["movie"].isin(df_m["title"])].copy()
    df_r = df_r.drop_duplicates(subset=["user_id", "movie"], keep="last")
    df_r = df_r[["user_id", "movie", "rating", "timestamp", "source", "reason"]]

    present_step(
        "3", "INTÉGRITÉ RÉFÉRENTIELLE DES ÉVALUATIONS (RATINGS)", df_raw_r, df_r,
        [
            ".isin() : Vérification croisée (Clés Étrangères). Supprime les votes liés à des films/users inexistants.",
            ".fillna('2026-06-01 ...') : Remplacement des dates manquantes de manière globale.",
            "drop_duplicates(subset=['user_id', 'movie'], keep='last') : Élimination des doubles votes."
        ]
    )
    df_r.to_csv(os.path.join(DATA_DIR, "clean_ratings.csv"), index=False)
    df_r.to_sql("ratings", conn, if_exists="append", index=False)
    conn.close()

    # ──────────────────────────────────────────────────────────────────────────
    # ÉTAPE 4 (NOUVELLE) : INITIALISATION DU CLUSTERING K-MEANS
    # ──────────────────────────────────────────────────────────────────────────
    print("\n" + "═"*85)
    print(" 🤖 ÉTAPE 4 : INITIALISATION DU CLUSTERING K-MEANS")
    print("═"*85)
    print(f"\n⚙️  Exécution du K-Means sur {len(df_u)} utilisateurs...")
    print(f"   Paramètres : K={database.CLUSTER_COUNT} clusters, vecteurs par genre")
    input("\n➡ Appuyez sur ENTRÉE pour lancer le clustering initial...")

    database.run_kmeans_clustering()

    # Vérification
    conn_check = database.get_connection()
    cursor_check = conn_check.cursor()
    cursor_check.execute("SELECT cluster_id, COUNT(*) as cnt FROM user_clusters GROUP BY cluster_id;")
    clusters = cursor_check.fetchall()
    conn_check.close()

    print("\n✨ RÉSULTAT DU CLUSTERING :")
    print("-" * 40)
    if clusters:
        for c in clusters:
            print(f"   Cluster #{c['cluster_id']} : {c['cnt']} utilisateurs")
    else:
        print("   ℹ️  Données insuffisantes pour le clustering (normal avec des données de test).")
    print("═"*85)

    print("\n🎉 [ETL SUCCESS] Démo terminée. Le catalogue est propre, réaliste et prêt !")
    print("    Tables : movies, users, ratings, user_tags, user_clusters")


if __name__ == "__main__":
    run_full_etl_pipeline()