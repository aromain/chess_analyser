import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed

from flask import Flask, jsonify, redirect, render_template, request
from werkzeug.utils import secure_filename

import chess
import chess.engine
import chess.pgn

# --- CONFIGURATION ---
# STOCKFISH_PATH = "stockfish/stockfish-macos-m1-apple-silicon"
STOCKFISH_PATH = "stockfish_linux/stockfish-ubuntu-x86-64-avx2"

UPLOAD_FOLDER = "uploads"
ALLOWED_EXTENSIONS = {"pgn"}

# Définissez le seuil de différence d'évaluation (en centipawns)
# 100 centipawns = avantage de 1 pion. Un seuil de 150 est un bon début.
EVAL_DIFFERENCE_THRESHOLD = 100

# Configuration de parallélisation des coups
# Utilise tous les cœurs CPU disponibles pour analyser plusieurs coups en parallèle
MAX_WORKERS = os.cpu_count() or 4  # Fallback à 4 si os.cpu_count() échoue
STOCKFISH_HASH_SIZE = (
    64  # Taille de la table de hachage en MB (optimisée pour analyse rapide)
)

# --- FIN DE LA CONFIGURATION ---

app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

# Stockage global pour la progression
analysis_progress = {}


def allowed_file(filename):
    """Vérifie si le fichier a une extension autorisée."""
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def configure_stockfish(engine):
    """Configure Stockfish pour une analyse rapide optimisée.

    Args:
        engine: Instance du moteur Stockfish
    """
    try:
        # Configuration optimisée pour analyse rapide
        engine.configure(
            {"Threads": 1}
        )  # Un seul thread par instance (on parallélise au niveau des coups)
        engine.configure({"Hash": STOCKFISH_HASH_SIZE})
        engine.configure({"Skill Level": 20})  # Niveau maximum
        engine.configure({"UCI_LimitStrength": False})

    except Exception as e:
        print(f"Erreur lors de la configuration de Stockfish: {e}")
        # Continue même si la configuration échoue


def analyze_position(position_data):
    """Analyse une position individuelle avec Stockfish avec sélection intelligente.

    Args:
        position_data: Dictionnaire contenant 'board', 'move_number', 'turn'

    Returns:
        Dictionnaire avec les résultats de l'analyse ou None si pas de moment critique
    """
    board = position_data["board"]
    move_number = position_data["move_number"]
    turn = position_data["turn"]

    print(f"Analyse de la position {move_number} du tour {turn}")

    try:
        # Créer une instance Stockfish pour cette analyse
        engine = chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH)
        configure_stockfish(engine)

        # 1. Analyser la position AVANT le coup pour vérifier si elle est nulle
        position_before = engine.analyse(board, chess.engine.Limit(time=0.3), multipv=1)
        if not position_before:
            engine.quit()
            return None

        # 2. Analyser les coups possibles pour cette position
        info = engine.analyse(board, chess.engine.Limit(time=0.5), multipv=3)

        if len(info) >= 2:
            score1 = info[0]["score"].white()
            score2 = info[1]["score"].white()

            eval1_cp = score1.score(mate_score=10000)
            eval2_cp = score2.score(mate_score=10000)

            if eval1_cp is not None and eval2_cp is not None:
                difference = abs(eval1_cp - eval2_cp)

                print(f"Difference: {difference}")

                # 3. Vérifier les conditions de sélection intelligente :
                # - Un coup est nettement meilleur que les autres
                # - Ce coup permet de prendre l'avantage (score > 50 centipawns)
                # - Les autres coups ne permettent pas de prendre l'avantage
                if difference > EVAL_DIFFERENCE_THRESHOLD and ((-50 < eval2_cp < 50)):
                    result = {
                        "fen": board.board_fen(),
                        "move_number": move_number,
                        "turn": turn,
                        "best_move": board.san(info[0]["pv"][0]),
                        "best_move_eval": str(score1),
                        "second_best_move": board.san(info[1]["pv"][0]),
                        "second_best_move_eval": str(score2),
                        "difference": difference / 100.0,
                    }
                    engine.quit()
                    return result

        engine.quit()
        return None

    except Exception as e:
        print(f"Erreur lors de l'analyse d'une position: {e}")
        if "engine" in locals():
            engine.quit()
        return None


def analyze_pgn_async(pgn_path, analysis_id):
    """
    Version asynchrone de l'analyse PGN avec parallélisation des coups.

    Args:
        pgn_path: Chemin vers le fichier PGN à analyser
        analysis_id: Identifiant unique pour cette analyse
    """
    # Initialiser la progression (en préservant le nom du fichier s'il existe déjà)
    if analysis_id not in analysis_progress:
        analysis_progress[analysis_id] = {
            "status": "starting",
            "progress": 0,
            "total_moves": 0,
            "current_move": 0,
            "results": None,
            "error": None,
        }
    else:
        # Préserver le nom du fichier et réinitialiser les autres champs
        filename = analysis_progress[analysis_id].get("filename", "fichier")
        analysis_progress[analysis_id].update(
            {
                "status": "starting",
                "progress": 0,
                "total_moves": 0,
                "current_move": 0,
                "results": None,
                "error": None,
            }
        )

    try:
        with open(pgn_path, encoding="utf-8") as pgn:
            all_games = []
            game_count = 0
            all_positions = []  # Toutes les positions à analyser

            # Première passe : collecter toutes les positions à analyser
            pgn.seek(0)
            while True:
                game = chess.pgn.read_game(pgn)
                if game is None:
                    break

                game_count += 1

                # Extraire les métadonnées de la partie
                game_info = {
                    "game_number": game_count,
                    "white": game.headers.get("White", "Inconnu"),
                    "black": game.headers.get("Black", "Inconnu"),
                    "result": game.headers.get("Result", "*"),
                    "date": game.headers.get("Date", "Inconnu"),
                    "event": game.headers.get("Event", "Inconnu"),
                    "critical_moments": [],
                }

                board = game.board()
                moves = list(game.mainline_moves())

                for move in moves:
                    # Ajouter la position AVANT de jouer le coup
                    position_data = {
                        "board": board.copy(),
                        "move_number": board.fullmove_number,
                        "turn": "Blancs" if board.turn == chess.WHITE else "Noirs",
                        "game_number": game_count,
                    }
                    all_positions.append(position_data)
                    # Ne pas stocker les positions dans game_info car elles contiennent des objets Board

                    # Jouer le coup pour la position suivante
                    board.push(move)

                all_games.append(game_info)

            if not all_games:
                analysis_progress[analysis_id][
                    "error"
                ] = "Le fichier PGN est invalide ou vide."
                return

            # Mettre à jour la progression
            total_positions = len(all_positions)
            analysis_progress[analysis_id]["total_moves"] = total_positions
            analysis_progress[analysis_id]["status"] = "analyzing"

            print(len(all_positions))

            # Analyser toutes les positions en parallèle
            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                # Soumettre toutes les tâches
                future_to_position = {
                    executor.submit(analyze_position, pos_data): pos_data
                    for pos_data in all_positions
                }

                completed = 0

                # Traiter les résultats au fur et à mesure
                for future in as_completed(future_to_position):
                    completed += 1

                    # Mettre à jour la progression
                    analysis_progress[analysis_id]["current_move"] = completed
                    analysis_progress[analysis_id]["progress"] = int(
                        completed / total_positions * 100
                    )

                    try:
                        result = future.result()
                        if result:
                            # Trouver la partie correspondante et ajouter le résultat
                            game_number = future_to_position[future]["game_number"]
                            for game in all_games:
                                if game["game_number"] == game_number:
                                    game["critical_moments"].append(result)
                                    break
                    except Exception as e:
                        print(f"Erreur lors de l'analyse d'une position: {e}")

        # Marquer comme terminé
        analysis_progress[analysis_id]["status"] = "completed"
        analysis_progress[analysis_id]["results"] = all_games

    except Exception as e:
        analysis_progress[analysis_id]["error"] = str(e)


@app.route("/", methods=["GET", "POST"])
def upload_file():
    """Gère l'upload et l'analyse des fichiers PGN."""
    if request.method == "POST":
        if "file" not in request.files:
            return redirect(request.url)

        file = request.files["file"]

        if file.filename == "":
            return redirect(request.url)

        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
            file.save(filepath)

            # Générer un ID unique pour cette analyse
            analysis_id = str(uuid.uuid4())

            # Stocker le nom du fichier dans la progression
            analysis_progress[analysis_id] = {
                "filename": filename,
                "status": "starting",
                "progress": 0,
                "total_moves": 0,
                "current_move": 0,
                "results": None,
                "error": None,
            }

            # Démarrer l'analyse en arrière-plan
            thread = threading.Thread(
                target=analyze_pgn_async, args=(filepath, analysis_id)
            )
            thread.daemon = True
            thread.start()

            return render_template(
                "index.html",
                analysis_id=analysis_id,
                filename=filename,
                workers=MAX_WORKERS,
                EVAL_DIFFERENCE_THRESHOLD=EVAL_DIFFERENCE_THRESHOLD,
            )

    return render_template(
        "index.html",
        workers=MAX_WORKERS,
        EVAL_DIFFERENCE_THRESHOLD=EVAL_DIFFERENCE_THRESHOLD,
    )


@app.route("/progress/<analysis_id>")
def get_progress(analysis_id):
    """Endpoint pour récupérer la progression de l'analyse.

    Args:
        analysis_id: Identifiant unique de l'analyse

    Returns:
        JSON avec les informations de progression
    """
    if analysis_id not in analysis_progress:
        return jsonify({"error": "Analyse non trouvée"}), 404

    return jsonify(analysis_progress[analysis_id])


@app.route("/results/<analysis_id>")
def get_results(analysis_id):
    """Endpoint pour récupérer les résultats finaux de l'analyse.

    Args:
        analysis_id: Identifiant unique de l'analyse

    Returns:
        Template avec les résultats ou JSON si encore en cours
    """
    if analysis_id not in analysis_progress:
        return jsonify({"error": "Analyse non trouvée"}), 404

    progress = analysis_progress[analysis_id]

    if progress["status"] == "completed":
        return render_template(
            "index.html",
            results=progress["results"],
            filename=progress.get("filename", "fichier"),
            workers=MAX_WORKERS,
            EVAL_DIFFERENCE_THRESHOLD=EVAL_DIFFERENCE_THRESHOLD,
        )
    elif progress["status"] == "error":
        return render_template(
            "index.html",
            error=progress["error"],
            workers=MAX_WORKERS,
            EVAL_DIFFERENCE_THRESHOLD=EVAL_DIFFERENCE_THRESHOLD,
        )
    else:
        return jsonify({"status": "still_processing"})


if __name__ == "__main__":
    if not os.path.exists(UPLOAD_FOLDER):
        os.makedirs(UPLOAD_FOLDER)
    # Vérification initiale du chemin de Stockfish pour aider l'utilisateur
    if not os.path.exists(STOCKFISH_PATH):
        print("--- ATTENTION ---")
        print(f"L'exécutable de Stockfish n'a pas été trouvé à " f"'{STOCKFISH_PATH}'.")
        print("Veuillez éditer la variable 'STOCKFISH_PATH' dans app.py.")
        print("-----------------")

    # Configuration pour l'hébergement
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_ENV") != "production"
    app.run(host="0.0.0.0", port=port, debug=debug)
