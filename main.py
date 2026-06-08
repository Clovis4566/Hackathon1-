"""
main.py
───────
Interface utilisateur principale (IHM Console).

Évolutions v3 :
  • Option [3] Modifier mon profil (pseudo, âge, tags, question secrète)
  • Option [4] Visualiser mes statistiques (appel viz.py)
  • Option [5] Déconnexion (anciennement [3])
  • save_user_feedback : gère le retour "updated" vs "inserted"
"""
import sys
import database
import onboarding
import charts


# ══════════════════════════════════════════════════════════════════════════════
# ÉCRANS D'ACCUEIL & UTILITAIRES
# ══════════════════════════════════════════════════════════════════════════════

def show_welcome_screen():
    print("\n" + "="*65)
    print("       BIENVENUE SUR VOTRE PLATEFORME CINÉMA       ")
    print("="*65)
    print(" [1] Me connecter à mon espace (via Clé de Session)")
    print(" [2] Créer un nouveau compte utilisateur")
    print(" [3] Récupérer une clé de session perdue")
    print(" [4] Quitter l'application")
    print("="*65)


def _mode_label(mode: str) -> str:
    return {
        "discovery": "DÉCOUVERTE (Cold Start)",
        "expert":    "SYSTÈME EXPERT",
        "ia":        "MOTEUR IA (Pearson + K-Means)",
    }.get(mode, mode.upper())


def _render_progress_bar(pct: int, width: int = 30) -> str:
    filled = int(pct / 100 * width)
    return "[" + "█" * filled + "░" * (width - filled) + f"] {pct}%"


# ══════════════════════════════════════════════════════════════════════════════
# PROCESSUS DE CONNEXION
# ══════════════════════════════════════════════════════════════════════════════

def handle_login_process():
    
    print(" ÉCRAN D'AUTHENTIFICATION SÉCURISÉE")
    

    code = input("Saisissez votre clé de session (ex: GEORGES-2135) ou [Q] pour annuler : ").strip()

    if code.upper() == 'Q':
        print("➔ Retour au menu principal.")
        return None

    if not code:
        print(" Erreur : La clé de session ne peut pas être vide.")
        return None

    user = database.find_user_by_code(code)

    if user:
      
        print(f" ACCÈS AUTORISÉ : Bienvenue {user['name'].upper()} !")
        print(f" Profil détecté : Amateur de films du genre [{user['profile_type'].upper()}]")
        
        return user
    else:
        print("\n ÉCHEC DE CONNEXION : Clé de session inconnue ou invalide.")
        print(" Conseil : Si vous avez oublié votre clé, utilisez l'option [3] du menu principal.")
        return None


# ══════════════════════════════════════════════════════════════════════════════
# RÉCUPÉRATION DE COMPTE
# ══════════════════════════════════════════════════════════════════════════════

def handle_account_recovery():
    print(" CELLULE DE RÉCUPÉRATION DE COMPTE")
    
    name = input("Quel est le prénom/pseudo lié à votre profil ? : ").strip()
    if not name:
        print(" Le prénom ne peut pas être vide.")
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
        print(f"\n Question de sécurité enregistrée : {row['secret_question']}")
        answer = input("Votre réponse secrète : ").strip().lower()
        if answer == row['secret_answer']:
            print("\n" + "✨"*20)
            print(" IDENTITÉ CONFIRMÉE !")
            print(f" Voici votre clé de session : {row['session_code']}")
            print("✨"*20)
        else:
            print(" Réponse incorrecte. Fin de la procédure de sécurité.")
    else:
        print(f" Aucun profil utilisateur trouvé au nom de '{name}'.")


# ══════════════════════════════════════════════════════════════════════════════
# MODIFICATION DU PROFIL
# ══════════════════════════════════════════════════════════════════════════════

def handle_edit_profile(user) -> dict:
    """
    Permet à l'utilisateur de modifier :
      - Son prénom / pseudo
      - Son âge
      - Ses tags de genres (relance le questionnaire onboarding)
      - Sa question / réponse secrète
    Retourne le dict user mis à jour (rechargé depuis la base).
    """
    while True:
        print(" MODIFICATION DE VOTRE PROFIL")
        
        print(f"  Profil actuel — {user['name']} | {user['age']} ans | {user['profile_type'].upper()}")

        tags = database.get_user_tags(user['user_id'])
        if tags:
            print(f"  Tags           — {' | '.join(t[0].upper() for t in tags)}")

        print()
        print(" [1] Modifier mon prénom / pseudo")
        print(" [2] Modifier mon âge")
        print(" [3] Modifier mes genres préférés (tags)")
        print(" [4] Modifier ma question de sécurité")
        print(" [Q] Retour sans modifier")
        print("─"*50)

        choice = input("Votre choix : ").strip().upper()

        if choice == "Q":
            break

        elif choice == "1":
            new_name = input("Nouveau prénom / pseudo : ").strip()
            if not new_name:
                print(" Le prénom ne peut pas être vide.")
                continue
            conn = database.get_connection()
            conn.execute(
                "UPDATE users SET name = ? WHERE user_id = ?;",
                (new_name, user['user_id'])
            )
            conn.commit()
            conn.close()
            print(f" Prénom mis à jour : {new_name}")

        elif choice == "2":
            age_input = input("Nouvel âge : ").strip()
            if not age_input.isdigit() or not (15 <= int(age_input) <= 99):
                print(" Âge invalide (doit être entre 15 et 99).")
                continue
            conn = database.get_connection()
            conn.execute(
                "UPDATE users SET age = ? WHERE user_id = ?;",
                (int(age_input), user['user_id'])
            )
            conn.commit()
            conn.close()
            print(f" Âge mis à jour : {age_input} ans")

        elif choice == "3":
            print("\n Relancement du questionnaire de genres...")
            all_tags, primary = onboarding.collect_user_preferences()
            database.save_user_tags(user['user_id'], all_tags)
            conn = database.get_connection()
            conn.execute(
                "UPDATE users SET profile_type = ? WHERE user_id = ?;",
                (primary, user['user_id'])
            )
            conn.commit()
            conn.close()
            print(f" Tags mis à jour : {' | '.join(t.upper() for t in all_tags)}")

        elif choice == "4":
            new_q = onboarding.show_numbered_menu(
                database.SECRET_QUESTIONS,
                "Choisissez votre nouvelle question de sécurité :"
            )
            new_a = input("Votre nouvelle réponse secrète : ").strip().lower()
            if not new_a:
                print(" La réponse ne peut pas être vide.")
                continue
            conn = database.get_connection()
            conn.execute(
                "UPDATE users SET secret_question = ?, secret_answer = ? WHERE user_id = ?;",
                (new_q, new_a, user['user_id'])
            )
            conn.commit()
            conn.close()
            print(" Question de sécurité mise à jour.")

        else:
            print(" Option invalide.")

    # Recharge le user depuis la base pour avoir les données fraîches
    updated_user = database.find_user_by_code(user['session_code'])
    return updated_user if updated_user else user


# ══════════════════════════════════════════════════════════════════════════════
# ESPACE MEMBRE — BOUCLE PRINCIPALE
# ══════════════════════════════════════════════════════════════════════════════

def run_main_application_loop(user):
    """Boucle interne de l'espace membre."""
    while True:
        maturity = database.get_user_maturity(user['user_id'])
        mode_lbl = _mode_label(maturity["mode"])
        progress = _render_progress_bar(maturity["progress_pct"])

        print("\n" + "═"*70)
        print(f"  ESPACE MEMBRE — {user['name'].upper()} | Genre : {user['profile_type'].upper()}")
        print(f" Moteur actif   : {mode_lbl}")
        if not maturity["is_ai_ready"]:
            print(f" Progression IA : {progress}  ({maturity['rating_count']}/{maturity['threshold']} évaluations)")
        else:
            print("  Moteur IA pleinement opérationnel !")
        print("═"*70)
        print(" [1] Consulter ma fiche profil & mon historique de visionnage")
        print(" [2] Lancer une demande de Recommandation Flash (Top 5)")
        print(" [3] Modifier mon profil")
        print(" [4] Visualiser mes statistiques de visionnage")
        print(" [5] Me déconnecter de mon espace")
        print("═"*70)

        choice = input("Votre choix (1-5) : ").strip()

        if choice == "1":
            _display_profile(user)

        elif choice == "2":
            _display_recommendations(user)

        elif choice == "3":
            user = handle_edit_profile(user)

        elif choice == "4":
            charts.show_charts_menu(
                user['user_id'],
                user['name']
            )

        elif choice == "5":
            print(f"\n Déconnexion réussie. À bientôt {user['name']} !")
            break

        else:
            print(" Option invalide. Entrez un chiffre de 1 à 5.")


# ══════════════════════════════════════════════════════════════════════════════
# SOUS-FONCTIONS D'AFFICHAGE
# ══════════════════════════════════════════════════════════════════════════════

def _display_profile(user):
    print("\n" + "─"*65)
    print(" VOS DONNÉES DE COMPTE")
    print("─"*65)
    print(f"  • ID Interne SQLite : {user['user_id']}")
    print(f"  • Prénom / Pseudo   : {user['name']}")
    print(f"  • Âge renseigné     : {user['age']} ans")
    print(f"  • Genre primaire    : {user['profile_type'].upper()}")

    tags = database.get_user_tags(user['user_id'])
    if tags:
        tags_str = " | ".join(f"{t[0].upper()} (×{t[1]:.0f})" for t in tags)
        print(f"  • Tags déclarés     : {tags_str}")

    maturity = database.get_user_maturity(user['user_id'])
    print(f"\n  Phase moteur    : {_mode_label(maturity['mode'])}")
    print(f"  Films évalués   : {maturity['rating_count']} / {maturity['threshold']} (seuil IA)")

    print("\n FILMS CONSULTÉS (dernières évaluations) :")
    history = database.get_user_viewing_history(user['user_id'])
    if history:
        for idx, row in enumerate(history, 1):
            print(f"   [{idx}] {row['movie']} | Note : {row['rating']}/5 (Le {row['timestamp']})")
    else:
        print("   Votre historique est vide. Vous n'avez pas encore noté de films.")

    print("─"*65)
    input("\n[Menu Profil] Appuyez sur ENTRÉE pour fermer l'affichage...")


def _display_recommendations(user):
    recs, mode_used, maturity = database.get_recommendations(
        user_id      = user['user_id'],
        profile_type = user['profile_type'],
        age          = user['age'],
        limit        = 5
    )

    if not recs:
        print(" Catalogue épuisé pour votre profil. Essayez de diversifier vos genres.")
        input("\nAppuyez sur ENTRÉE pour revenir...")
        return

    print(f"\nMOTEUR : {_mode_label(mode_used)}")
    print(f"   TOP 5 SUGGESTIONS — Fraîches & Personnalisées")
    print(f"{'Rang':<5} | {'Titre du Film':<28} | {'Note':<6} | {'Réalisateur'}")
    print("-" * 65)

    displayed_movies = []
    for idx, movie in enumerate(recs, 1):
        avg = movie.get('avg_rating', 0) or 0
        print(f"#{idx:<3} | {movie['title']:<28} | {avg:.1f}/5  | {movie.get('director', 'N/A')}")
        displayed_movies.append(movie['title'])
        database.save_recommendation(user['user_id'], movie['title'])

    while True:
        print(" ENQUÊTE DE SATISFACTION (En continu)")
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
                    result = database.save_user_feedback(user['user_id'], chosen_title, satisfaction_score)
                    if result == "inserted":
                        new_maturity = database.get_user_maturity(user['user_id'])
                        print(f"  Enregistré ! Note de {satisfaction_score}/5 pour '{chosen_title}'.")
                        if not new_maturity["is_ai_ready"]:
                            bar = _render_progress_bar(new_maturity["progress_pct"], width=20)
                            print(f"  Progression IA : {bar} ({new_maturity['rating_count']}/{new_maturity['threshold']})")
                        elif new_maturity["rating_count"] == new_maturity["threshold"]:
                            print("  SEUIL ATTEINT ! Le moteur IA est maintenant actif pour vous !")
                    elif result == "updated":
                        print(f" Note mise à jour : {satisfaction_score}/5 pour '{chosen_title}' (pas de doublon comptabilisé).")
                    else:
                        print("  Erreur technique lors de l'enregistrement.")
                else:
                    print("  Note incorrecte (doit être entre 1 et 5).")
            else:
                print("  Ce numéro n'est pas dans le Top 5.")
        else:
            print("  Entrée invalide. Tapez un chiffre de 1 à 5, ou 'Q' pour quitter.")

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
            print(" Option inconnue. Veuillez choisir un chiffre entre 1 et 4.")
            input("\nAppuyez sur ENTRÉE pour continuer...")


if __name__ == "__main__":
    main()