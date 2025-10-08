# Analyseur de Moments Critiques PGN

Une application web pour analyser les parties d'échecs et identifier les moments critiques où un coup change l'issue de la partie.

## Fonctionnalités

- 🎯 **Sélection intelligente** : Détecte uniquement les coups qui permettent de prendre l'avantage à partir d'une position nulle
- ⚡ **Parallélisation** : Utilise tous les cœurs CPU pour une analyse rapide
- 📊 **Multi-parties** : Analyse plusieurs parties dans un même fichier PGN
- 🎨 **Interface moderne** : Barre de progression en temps réel et échiquiers interactifs

## Déploiement

### Railway (Recommandé)
1. Fork ce repository
2. Créer un compte sur [railway.app](https://railway.app)
3. Connecter votre repository
4. Railway déploie automatiquement

### Render
1. Fork ce repository
2. Créer un compte sur [render.com](https://render.com)
3. Créer un nouveau "Web Service"
4. Connecter votre repository
5. Render déploie automatiquement

## Utilisation

1. Uploadez un fichier PGN
2. L'application analyse automatiquement toutes les parties
3. Les moments critiques sont affichés avec des échiquiers interactifs

## Configuration

L'application utilise Stockfish pour l'analyse. Le chemin vers l'exécutable est configuré dans `app.py` :

```python
STOCKFISH_PATH = "stockfish/stockfish-macos-m1-apple-silicon"
```

Pour d'autres plateformes, modifiez ce chemin selon votre installation de Stockfish.
# chess_analyser
# chess_analyser
