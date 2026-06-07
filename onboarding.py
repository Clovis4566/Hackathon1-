"""
onboarding.py
─────────────
Inscription, exploration des préférences et quiz de découverte.

Système de 10 questions forcées (Cold Start Quiz) :
  • 10 films tirés du catalogue, répartis sur TOUS les genres disponibles
  • Sélection aléatoire dans la moyenne (pas que les mieux notés)
  • L'utilisateur note chaque film : "Vu et aimé / Vu mais pas aimé / Pas vu"
  • Les notes sont enregistrées avec source='discovery_quiz'
  • Ces données alimentent immédiatement le Système Expert dès la connexion
"""
import random
import database


# ══════════════════════════════════════════════════════════════════════════════
# UTILITAIRES D'AFFICHAGE
# ══════════════════════════════════════════════════════════════════════════════

def show_numbered_menu(options, prompt_text, multi=False) -> list | str:
    """
    Affiche un menu numéroté.
    Si multi=True, l'utilisateur peut choisir plusieurs numéros séparés par des virgules.
    Retourne une liste si multi=True, une chaîne sinon.
    """
    while True:
        print(f"\n{prompt_text}")
        for idx, option in enumerate(options, 1):
            print(f"  [{idx}] {option.upper()}")

        if multi:
            print("  (Entrez plusieurs numéros séparés par des virgules, ex: 1,3)")

        choice = input("Votre sélection : ").strip()

        if multi:
            parts = [p.strip() for p in choice.split(",")]
            selected = []
            valid = True
            for p in parts:
                if p.isdigit():
                    idx_chosen = int(p) - 1
                    if 0 <= idx_chosen < len(options):
                        if options[idx_chosen] not in selected:
                            selected.append(options[idx_chosen])
                    else:
                        valid = False
                        break
                else:
                    valid = False
                    break
            if valid and selected:
                return selected
        else:
            if choice.isdigit():
                idx_chosen = int(choice) - 1
                if 0 <= idx_chosen < len(options):
                    return options[idx_chosen]

        print("❌ Choix invalide. Veuillez sélectionner un ou plusieurs numéros valides.")


# ══════════════════════════════════════════════════════════════════════════════
# ÉTAPE 1 : GENRES (inchangée)
# ══════════════════════════════════════════════════════════════════════════════

def collect_user_preferences() -> tuple:
    """
    Explore les goûts cinématographiques de base.
    Retourne (liste_de_tags, genre_primaire).
    """
    print("\n" + "═"*60)
    print(" 🎬 EXPLORATION DE VOS GOÛTS CINÉMATOGRAPHIQUES")
    print("═"*60)
    print(" Vos réponses activent le moteur de recommandation personnalisé.")
    print(" Plus vous êtes précis, plus les suggestions seront pertinentes.\n")

    available_genres = database.get_all_unique_genres()
    if not available_genres:
        available_genres = ["sci-fi", "action", "thriller", "drama", "comedy", "horror", "romance", "animation"]

    # Genre primaire
    primary = show_numbered_menu(
        available_genres,
        "① Quel est le genre que vous regardez le PLUS souvent ?",
        multi=False
    )

    # Genres secondaires
    remaining = [g for g in available_genres if g != primary]
    print("\n② Choisissez un ou plusieurs genres SECONDAIRES qui vous intéressent (facultatif).")
    print("   [0] Passer cette étape")

    secondary_tags = []
    skip_input = input("   Appuyez sur [0] pour passer, ou ENTRÉE pour choisir : ").strip()
    if skip_input != "0":
        secondary_tags = show_numbered_menu(
            remaining,
            "Sélectionnez vos genres secondaires (ex: 1,3,5) :",
            multi=True
        )
        if isinstance(secondary_tags, str):
            secondary_tags = [secondary_tags]

    all_tags = [primary] + secondary_tags
    return all_tags, primary


# ══════════════════════════════════════════════════════════════════════════════
# ÉTAPE 2 : QUIZ DE DÉCOUVERTE — 10 films à noter
# ══════════════════════════════════════════════════════════════════════════════

def _pick_quiz_films(all_tags: list, n: int = 10) -> list:
    """
    Sélectionne n films du catalogue pour le quiz.

    Stratégie :
      - On répartit les slots entre tous les genres disponibles (pas seulement
        les genres déclarés) pour maximiser la diversité.
      - Dans chaque genre, on tire au hasard dans un pool LARGE (pas
        uniquement les mieux notés) pour éviter de toujours proposer les
        mêmes blockbusters.
      - Les genres déclarés par l'utilisateur ont 1 slot supplémentaire.
    """
    conn = database.get_connection()
    cursor = conn.cursor()

    all_genres = database.get_all_unique_genres()
    if not all_genres:
        conn.close()
        return []

    # Répartition de base : 1 film par genre, puis on distribue les restes
    slots = {g: 1 for g in all_genres}
    declared_genres = [t.lower() for t in all_tags]
    extra = n - len(all_genres)
    for g in declared_genres:
        if g in slots and extra > 0:
            slots[g] += 1
            extra -= 1
    # Si encore des slots libres, on les distribue aléatoirement
    remaining_genres = list(all_genres)
    random.shuffle(remaining_genres)
    for g in remaining_genres:
        if extra <= 0:
            break
        slots[g] += 1
        extra -= 1

    selected = []
    for genre, count in slots.items():
        # Pool large : tous les films du genre (pas de filtre avg_rating)
        cursor.execute("""
            SELECT title, avg_rating, director, year
            FROM movies
            WHERE genre = ?
            ORDER BY RANDOM()
            LIMIT 30;
        """, (genre,))
        pool = cursor.fetchall()
        # On tire `count` films au hasard dans ce pool
        picks = random.sample(pool, min(count, len(pool)))
        selected.extend([dict(p) for p in picks])

    conn.close()
    random.shuffle(selected)   # mélange final pour ne pas grouper par genre
    return selected[:n]


def run_discovery_quiz(user_id: str, all_tags: list) -> int:
    """
    Lance le quiz de 10 films.
    Pour chaque film, l'utilisateur choisit parmi :
      [1] Vu et j'ai adoré  (→ note 5)
      [2] Vu et j'ai aimé   (→ note 4)
      [3] Vu, moyen         (→ note 3)
      [4] Vu, pas aimé      (→ note 2)
      [5] Jamais vu         (→ ignoré, pas de note)

    Retourne le nombre de films effectivement notés.
    """
    print("\n" + "═"*65)
    print(" 🎬 QUIZ DE DÉCOUVERTE — 10 Films à évaluer")
    print("═"*65)
    print(" Pour chaque film, dites-nous si vous l'avez vu et ce que vous en pensez.")
    print(" Vos réponses calibrent immédiatement le moteur de recommandation.")
    print(" (Si vous ne l'avez jamais vu, choisissez [5] — aucune note ne sera enregistrée)")
    print("═"*65)

    films = _pick_quiz_films(all_tags, n=10)
    if not films:
        print("\n⚠️  Le catalogue est vide. Lancez d'abord clean_data.py.")
        return 0

    CHOICES = [
        ("Vu et j'ai adoré",   5.0),
        ("Vu et j'ai bien aimé", 4.0),
        ("Vu, c'était moyen",  3.0),
        ("Vu, je n'ai pas aimé", 2.0),
        ("Je ne l'ai jamais vu", None),   # Pas de note
    ]

    rated_count = 0

    for i, film in enumerate(films, 1):
        print(f"\n  ┌─ Film {i:>2}/10 ──────────────────────────────────────────")
        print(f"  │  🎥  {film['title']}")
        print(f"  │  🎬  Réalisateur : {film.get('director', 'N/A')}")
        avg = film.get('avg_rating') or 0
        stars = "★" * int(round(avg)) + "☆" * (5 - int(round(avg)))
        print(f"  │  ⭐  Note catalogue : {stars}  ({avg:.1f}/5)")
        print(f"  └──────────────────────────────────────────────────────")

        while True:
            for idx, (label, _) in enumerate(CHOICES, 1):
                print(f"    [{idx}] {label}")
            ans = input("  Votre réponse : ").strip()
            if ans.isdigit() and 1 <= int(ans) <= len(CHOICES):
                label, note = CHOICES[int(ans) - 1]
                if note is not None:
                    database.save_discovery_rating(user_id, film['title'], note)
                    rated_count += 1
                    print(f"  ✅ Note {note:.0f}/5 enregistrée pour « {film['title']} »")
                else:
                    print(f"  ⏭️  Film ignoré (jamais vu).")
                break
            print("  ❌ Répondez avec un chiffre entre 1 et 5.")

    print(f"\n  🎯 Quiz terminé ! {rated_count} film(s) noté(s).")
    print("  Ces données alimentent déjà le moteur de recommandation.")
    return rated_count


# ══════════════════════════════════════════════════════════════════════════════
# POINT D'ENTRÉE : INSCRIPTION COMPLÈTE
# ══════════════════════════════════════════════════════════════════════════════

def trigger_user_registration() -> str | None:
    """
    Processus complet d'inscription :
      1. Infos de base (nom, âge)
      2. Sélection des genres (primaire + secondaires)
      3. Quiz de découverte (10 films)
      4. Question secrète
    Retourne le session_code généré en cas de succès, None sinon.
    """
    print("\n" + "═"*60)
    print(" 👤 CRÉATION DE VOTRE ESPACE PERSONNEL")
    print("═"*60)

    name = input("Comment souhaitez-vous qu'on vous appelle ? (Prénom/Pseudo) : ").strip()
    while not name:
        name = input("Le prénom ne peut pas être vide : ").strip()

    age_input = input("Quel âge avez-vous ? : ").strip()
    age = int(age_input) if age_input.isdigit() else 23

    all_tags, profile_type = collect_user_preferences()

    print("\n🔒 SÉCURITÉ DE VOTRE COMPTE")
    question_choisie = show_numbered_menu(
        database.SECRET_QUESTIONS,
        "Choisissez une question de récupération :",
        multi=False
    )
    reponse = input("Votre réponse secrète : ").strip().lower()

    new_id = f"U{random.randint(600, 999)}"
    generated_session_code = f"{name.upper()}-{random.randint(1000, 9999)}"

    success = database.register_new_user(
        new_id, name, age, profile_type,
        generated_session_code, question_choisie, reponse
    )

    if not success:
        print("\n❌ Erreur lors de la création du compte (ID ou session déjà utilisé). Réessayez.")
        return None

    # Persistance des tags multi-genres
    database.save_user_tags(new_id, all_tags)

    print("\n" + "🎉"*20)
    print(" BIENVENUE DANS LA COMMUNAUTÉ !")
    print(f" Votre identifiant unique       : {new_id}")
    print(f" Votre clé de connexion         : {generated_session_code}")
    print(f" Genres enregistrés             : {' | '.join(t.upper() for t in all_tags)}")
    print("🎉"*20)

    # ── Quiz de découverte ────────────────────────────────────────────────────
    print("\n" + "🔭"*20)
    print(" QUIZ DE DÉCOUVERTE — Étape indispensable")
    print(" Avant vos premières recommandations, répondez à 10 questions rapides")
    print(" sur des films que vous connaissez (ou pas).")
    print(" Cela permet au moteur de vous connaître dès le premier jour.")
    print("🔭"*20)
    input("\nAppuyez sur ENTRÉE pour lancer le quiz...")

    rated = run_discovery_quiz(new_id, all_tags)

    # Message final selon combien de films ont été notés
    print("\n" + "─"*60)
    if rated >= database.MATURITY_THRESHOLD:
        print(f" 🚀 Excellent ! {rated} films notés — le Système Expert est déjà actif !")
    elif rated > 0:
        print(f" ⚙️  {rated} films notés — encore {database.MATURITY_THRESHOLD - rated} pour activer le Système Expert.")
    else:
        print(" 🔭 Aucun film noté — mode Découverte actif pour vos premières reco.")
    print(" Connectez-vous maintenant pour recevoir vos premières recommandations.")
    print("─"*60)

    input("\nAppuyez sur ENTRÉE pour continuer...")