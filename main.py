"""
main.py
───────
Interface utilisateur principale (IHM Console).
Focus exclusif sur le processus d'échange, la persistance des menus
et la sécurité de la connexion. Sans effacement de terminal.

Évolutions vs version initiale :
  • Affichage du mode actif (Découverte / Système Expert / IA) dans l'espace membre
  • Barre de progression vers la phase IA
  • Appel à database.get_recommendations() à la place de get_movies_by_genre()
  • Indicateur visuel du moteur utilisé sur chaque résultat
"""
import sys
import database
import onboarding


# ══════════════════════════════════════════════════════════════════════════════
# VISUALISATIONS (ASCII — sans dépendance externe)
# ══════════════════════════════════════════════════════════════════════════════

def _display_genre_distribution(user_id):
    """Diagramme en barres ASCII : répartition des genres dans l'historique."""
    conn = database.get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT m.genre, COUNT(*) as cnt
        FROM ratings r
        JOIN movies m ON r.movie = m.title
        WHERE r.user_id = ?
        GROUP BY m.genre
        ORDER BY cnt DESC;
    """, (user_id,))
    rows = cursor.fetchall()
    conn.close()

    print("\n" + "═"*60)
    print(" 📊 DISTRIBUTION DE VOS GENRES REGARDÉS")
    print("═"*60)

    if not rows:
        print("   ℹ️  Aucune évaluation enregistrée pour le moment.")
        input("\nAppuyez sur ENTRÉE pour continuer...")
        return

    total = sum(r["cnt"] for r in rows)
    bar_width = 30
    for r in rows:
        pct = r["cnt"] / total * 100
        filled = int(pct / 100 * bar_width)
        bar = "█" * filled + "░" * (bar_width - filled)
        print(f"  {r['genre'].upper():<12} [{bar}] {r['cnt']:>3} film(s)  ({pct:.0f}%)")

    print("═"*60)
    input("\nAppuyez sur ENTRÉE pour continuer...")


def _display_rating_trend(user_id):
    """Graphique ASCII : évolution des notes au fil du temps."""
    conn = database.get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT movie, rating, timestamp
        FROM ratings
        WHERE user_id = ? AND source = 'system_expert_feedback'
        ORDER BY timestamp ASC;
    """, (user_id,))
    rows = cursor.fetchall()
    conn.close()

    print("\n" + "═"*65)
    print(" 📈 ÉVOLUTION DE VOS NOTES AU FIL DU TEMPS")
    print("═"*65)

    if not rows:
        print("   ℹ️  Aucune note enregistrée pour le moment.")
        input("\nAppuyez sur ENTRÉE pour continuer...")
        return

    chart_height = 5   # Lignes de 1 à 5
    print(f"\n   Note")
    for y in range(5, 0, -1):
        line = f"  {y} │"
        for r in rows:
            rating = int(round(r["rating"]))
            line += " ●" if rating == y else "  "
        print(line)
    print("    └" + "──" * len(rows))
    print("      " + "".join(f"{i+1:<2}" for i in range(len(rows))))
    print("      (ordre chronologique des évaluations)")

    # Résumé statistique
    ratings = [r["rating"] for r in rows]
    avg = sum(ratings) / len(ratings)
    trend = "📈 En hausse" if ratings[-1] > ratings[0] else ("📉 En baisse" if ratings[-1] < ratings[0] else "➡️  Stable")
    print(f"\n  Moyenne : {avg:.2f}/5  |  Tendance : {trend}  |  Films notés : {len(rows)}")
    print("═"*65)
    input("\nAppuyez sur ENTRÉE pour continuer...")


# ══════════════════════════════════════════════════════════════════════════════
# ÉCRANS D'ACCUEIL & UTILITAIRES
# ══════════════════════════════════════════════════════════════════════════════

def show_welcome_screen():
    print("\n" + "="*65)
    print(" 🎬       BIENVENUE SUR VOTRE PLATEFORME CINÉMA       🎬")
    print("="*65)
    print(" [1] Me connecter à mon espace (via Clé de Session)")
    print(" [2] Créer un nouveau compte utilisateur")
    print(" [3] Récupérer une clé de session perdue")
    print(" [4] Quitter l'application")
    print("="*65)


def _mode_label(mode: str) -> str:
    """Retourne un label coloré/emoji selon le mode actif."""
    return {
        "discovery": "🔭 DÉCOUVERTE (Cold Start)",
        "expert":    "⚙️  SYSTÈME EXPERT",
        "ia":        "🤖 MOTEUR IA (Pearson + K-Means)",
    }.get(mode, mode.upper())


def _render_progress_bar(pct: int, width: int = 30) -> str:
    filled = int(pct / 100 * width)
    return "[" + "█" * filled + "░" * (width - filled) + f"] {pct}%"


# ══════════════════════════════════════════════════════════════════════════════
# PROCESSUS DE CONNEXION
# ══════════════════════════════════════════════════════════════════════════════

def handle_login_process():
    print("\n" + "🔑"*15)
    print(" ÉCRAN D'AUTHENTIFICATION SÉCURISÉE")
    print("🔑"*15)

    code = input("Saisissez votre clé de session (ex: GEORGES-2135) ou [Q] pour annuler : ").strip()

    if code.upper() == 'Q':
        print("➔ Retour au menu principal.")
        return None

    if not code:
        print("❌ Erreur : La clé de session ne peut pas être vide.")
        return None

    user = database.find_user_by_code(code)

    if user:
        print("\n" + "🔓"*20)
        print(f" ACCÈS AUTORISÉ : Bienvenue {user['name'].upper()} !")
        print(f" Profil détecté : Amateur de films du genre [{user['profile_type'].upper()}]")
        print("🔓"*20)
        return user
    else:
        print("\n❌ ÉCHEC DE CONNEXION : Clé de session inconnue ou invalide.")
        print("💡 Conseil : Si vous avez oublié votre clé, utilisez l'option [3] du menu principal.")
        return None


# ══════════════════════════════════════════════════════════════════════════════
# RÉCUPÉRATION DE COMPTE
# ══════════════════════════════════════════════════════════════════════════════

def handle_account_recovery():
    print("\n" + "🛟"*15)
    print(" CELLULE DE RÉCUPÉRATION DE COMPTE")
    print("🛟"*15)

    name = input("Quel est le prénom/pseudo lié à votre profil ? : ").strip()
    if not name:
        print("❌ Le prénom ne peut pas être vide.")
        return

    conn = database.get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT secret_question, secret_answer, session_code FROM users "
        "WHERE UPPER(TRIM(name)) = UPPER(TRIM(?));",
        (name,)
    )
    row = cursor.fetchone()
    conn.close()

    if row:
        print(f"\n❓ Question de sécurité enregistrée : {row['secret_question']}")
        answer = input("Votre réponse secrète : ").strip().lower()
        if answer == row['secret_answer']:
            print("\n" + "✨"*20)
            print(" IDENTITÉ CONFIRMÉE !")
            print(f" Voici votre clé de session : {row['session_code']}")
            print("✨"*20)
        else:
            print("❌ Réponse incorrecte. Fin de la procédure de sécurité.")
    else:
        print(f"❌ Aucun profil utilisateur trouvé au nom de '{name}'.")


# ══════════════════════════════════════════════════════════════════════════════
# ESPACE MEMBRE — BOUCLE PRINCIPALE
# ══════════════════════════════════════════════════════════════════════════════

def run_main_application_loop(user):
    """Boucle interne de l'espace membre. Aucun terminal ne s'efface ici."""
    while True:
        # Récupération de la maturité en temps réel
        maturity  = database.get_user_maturity(user['user_id'])
        mode_lbl  = _mode_label(maturity["mode"])
        progress  = _render_progress_bar(maturity["progress_pct"])

        print("\n" + "═"*70)
        print(f" 👤 ESPACE MEMBRE — {user['name'].upper()} | Genre : {user['profile_type'].upper()}")
        print(f" Moteur actif   : {mode_lbl}")
        if not maturity["is_ai_ready"]:
            print(f" Progression IA : {progress}  ({maturity['rating_count']}/{maturity['threshold']} évaluations)")
        else:
            print(" ✅ Moteur IA pleinement opérationnel !")
        print("═"*70)
        print(" [1] Consulter ma fiche profil & mon historique de visionnage")
        print(" [2] Lancer une demande de Recommandation Flash (Top 5)")
        print(" [3] 📊 Visualiser mes statistiques (genres & tendances)")
        print(" [4] Me déconnecter de mon espace")
        print("═"*70)

        choice = input("Votre choix (1-4) : ").strip()

        # ── Option 1 : Profil ────────────────────────────────────────────────
        if choice == "1":
            _display_profile(user)

        # ── Option 2 : Recommandations ───────────────────────────────────────
        elif choice == "2":
            _display_recommendations(user)

        # ── Option 3 : Visualisations ────────────────────────────────────────
        elif choice == "3":
            _display_genre_distribution(user['user_id'])
            _display_rating_trend(user['user_id'])

        # ── Option 4 : Déconnexion ───────────────────────────────────────────
        elif choice == "4":
            print(f"\n👋 Déconnexion réussie. À bientôt {user['name']} !")
            break

        else:
            print("❌ Option invalide. Entrez 1, 2, 3 ou 4.")


# ══════════════════════════════════════════════════════════════════════════════
# SOUS-FONCTIONS D'AFFICHAGE
# ══════════════════════════════════════════════════════════════════════════════

def _display_profile(user):
    print("\n" + "─"*65)
    print(" 📋 VOS DONNÉES DE COMPTE")
    print("─"*65)
    print(f"  • ID Interne SQLite : {user['user_id']}")
    print(f"  • Prénom / Pseudo   : {user['name']}")
    print(f"  • Âge renseigné     : {user['age']} ans")
    print(f"  • Genre primaire    : {user['profile_type'].upper()}")

    # Tags multi-genres
    tags = database.get_user_tags(user['user_id'])
    if tags:
        tags_str = " | ".join(f"{t[0].upper()} (×{t[1]:.0f})" for t in tags)
        print(f"  • Tags déclarés     : {tags_str}")

    # Maturité
    maturity = database.get_user_maturity(user['user_id'])
    print(f"\n  🧠 Phase moteur    : {_mode_label(maturity['mode'])}")
    print(f"  📊 Films évalués   : {maturity['rating_count']} / {maturity['threshold']} (seuil IA)")

    print("\n 🍿 FILMS CONSULTÉS (dernières évaluations) :")
    history = database.get_user_viewing_history(user['user_id'])
    if history:
        for idx, row in enumerate(history, 1):
            source_label = "🎬 Quiz" if row['source'] == 'discovery_quiz' else "⭐ Reco"
            print(f"   [{idx}] {row['movie']} | Note : {row['rating']}/5  {source_label}  (Le {row['timestamp']})")
    else:
        print("   ℹ️  Votre historique est vide. Vous n'avez pas encore noté de films.")

    print("─"*65)
    input("\n[Menu Profil] Appuyez sur ENTRÉE pour fermer l'affichage...")


def _display_recommendations(user):
    """Affiche le Top 5 et lance la boucle de notation en série."""

    # ── Appel au moteur hybride ───────────────────────────────────────────────
    recs, mode_used, maturity = database.get_recommendations(
        user_id      = user['user_id'],
        profile_type = user['profile_type'],
        age          = user['age'],
        limit        = 5
    )

    if not recs:
        print(" ℹ️ Catalogue épuisé pour votre profil. Essayez de diversifier vos genres.")
        input("\nAppuyez sur ENTRÉE pour revenir...")
        return

    # ── Affichage du moteur utilisé ──────────────────────────────────────────
    print(f"\n🔮 MOTEUR : {_mode_label(mode_used)}")
    print(f"   TOP 5 SUGGESTIONS — Fraîches & Personnalisées")
    print(f"{'Rang':<5} | {'Titre du Film':<28} | {'Note':<6} | {'Réalisateur'}")
    print("-" * 65)

    displayed_movies = []
    for idx, movie in enumerate(recs, 1):
        avg = movie.get('avg_rating', 0) or 0
        print(f"#{idx:<3} | {movie['title']:<28} | {avg:.1f}/5  | {movie.get('director', 'N/A')}")
        displayed_movies.append(movie['title'])
        database.save_recommendation(user['user_id'], movie['title'])

    # ── Boucle de notation (inchangée dans sa logique) ───────────────────────
    while True:
        print("\n" + "⚙️ " + "─"*52 + " ⚙️")
        print(" 🤖 ENQUÊTE DE SATISFACTION (En continu)")
        print(" Y a-t-il un film de cette liste que vous souhaitez évaluer ?")

        feedback_choice = input(" Renseignez le numéro du film (1-5) ou [Q] pour arrêter : ").strip()

        if feedback_choice.upper() == 'Q':
            print(" ➔ Fin de la session d'évaluation.")
            break

        if feedback_choice.isdigit():
            movie_idx = int(feedback_choice) - 1
            if 0 <= movie_idx < len(displayed_movies):
                chosen_title = displayed_movies[movie_idx]

                print(f"\n Vous évaluez : '{chosen_title}'")
                print(" Niveau de satisfaction :")
                print("  [1] Très déçu  [2] Peu convaincu  [3] Moyen  [4] Satisfait  [5] Excellent !")

                satisfaction_score = input(" Votre note (1-5) : ").strip()
                if satisfaction_score.isdigit() and 1 <= int(satisfaction_score) <= 5:
                    success = database.save_user_feedback(user['user_id'], chosen_title, satisfaction_score)
                    if success == "already_rated":
                        print(f" ⚠️  Vous avez déjà noté '{chosen_title}'. Chaque film ne peut être évalué qu'une seule fois.")
                    elif success:
                        print(f" 🎉 Enregistré ! Note de {satisfaction_score}/5 ajoutée pour '{chosen_title}'.")
                        # Affiche la progression vers la phase IA après chaque note
                        new_maturity = database.get_user_maturity(user['user_id'])
                        if not new_maturity["is_ai_ready"]:
                            bar = _render_progress_bar(new_maturity["progress_pct"], width=20)
                            print(f" 📈 Progression IA : {bar} ({new_maturity['rating_count']}/{new_maturity['threshold']})")
                        else:
                            if new_maturity["rating_count"] == new_maturity["threshold"]:
                                print(" 🚀 SEUIL ATTEINT ! Le moteur IA est maintenant actif pour vous !")
                    else:
                        print(" ❌ Erreur technique lors de l'enregistrement.")
                else:
                    print(" ❌ Note incorrecte (doit être entre 1 et 5).")
            else:
                print(" ❌ Ce numéro n'est pas dans le Top 5.")
        else:
            print(" ❌ Entrée invalide. Tapez un chiffre de 1 à 5, ou 'Q' pour quitter.")

    print("═"*70)
    input("\n[Menu Recommandation] Appuyez sur ENTRÉE pour revenir aux options...")


# ══════════════════════════════════════════════════════════════════════════════
# POINT D'ENTRÉE
# ══════════════════════════════════════════════════════════════════════════════

def main():
    database.create_tables()

    while True:
        show_welcome_screen()
        choice = input("Sélectionnez une action (1-4) : ").strip()

        if choice == "1":
            user_session = handle_login_process()
            if user_session:
                run_main_application_loop(user_session)

        elif choice == "2":
            session_token = onboarding.trigger_user_registration()
            if session_token:
                user_session = database.find_user_by_code(session_token)
                if user_session:
                    run_main_application_loop(user_session)

        elif choice == "3":
            handle_account_recovery()

        elif choice == "4":
            print("\nArrêt des services. Merci d'avoir utilisé l'application !")
            sys.exit(0)

        else:
            print("❌ Option inconnue. Veuillez choisir un chiffre entre 1 et 4.")
            input("\nAppuyez sur ENTRÉE pour continuer...")


if __name__ == "__main__":
    main()