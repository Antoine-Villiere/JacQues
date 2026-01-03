# Jacques Assistant (Dash)

Jacques est un assistant complet en Python + Dash. Il gere plusieurs conversations, conserve la memoire du contexte, ingere des documents (PDF, Word, Excel, CSV), modifie ou cree des fichiers Word/Excel, analyse des images, utilise un systeme de RAG, peut faire du web browsing, et peut generer des images. Le LLM passe par LiteLLM (Groq) et peut piloter les outils automatiquement.

## Demarrage rapide

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python app.py
```

Ouvrir `http://127.0.0.1:8050`.

## Configuration (.env)

```
GROQ_API_KEY=your_key
LITELLM_PROVIDER=
LITELLM_API_KEY=
LITELLM_API_BASE=
TEXT_MODEL=groq/openai/gpt-oss-120b
REASONING_MODEL=groq/openai/gpt-oss-120b
VISION_MODEL=groq/meta-llama/llama-4-maverick-17b-128e-instruct
VISION_ENABLED=true
IMAGE_PROVIDER=openai
IMAGE_API_KEY=your_key
IMAGE_MODEL=gpt-image-1
WEB_TIMEOUT=10
BRAVE_API_KEY=your_key
BRAVE_COUNTRY=FR
BRAVE_SEARCH_LANG=fr
RAG_TOP_K=4
MAX_HISTORY_MESSAGES=40
MAX_TOOL_CALLS=4
LLM_STREAMING=true
APP_BASE_URL=http://127.0.0.1:8050
ONLYOFFICE_URL=http://127.0.0.1:8080
ONLYOFFICE_JWT=
```

Si aucune cle API n'est fournie, Jacques reste utilisable mais repond avec un mode degrade (RAG + contexte).
`GROQ_API_KEY` suffit pour Groq; `LITELLM_PROVIDER` et `LITELLM_API_KEY` sont optionnels.
`IMAGE_API_KEY` sert a la generation d'images (OpenAI par defaut).
`BRAVE_API_KEY` active Brave Web Search (remplace DuckDuckGo).
`LLM_STREAMING=true` active le mode streaming LiteLLM (affichage token par token).
`APP_BASE_URL` doit etre accessible par OnlyOffice (pour recuperer les fichiers).
`ONLYOFFICE_URL` pointe vers le Document Server OnlyOffice.
`ONLYOFFICE_JWT` (optionnel) si votre Document Server utilise JWT.

## Fonctionnalites

- Multi-conversations avec persistance SQLite.
- RAG local avec TF-IDF.
- Ingestion PDF, Word, Excel, CSV.
- Modifications Word/Excel via commandes (tools).
- Edition Word/Excel depuis l'interface (offcanvas fichiers) avec preservation du formatage.
- Option: viewer/editeur OnlyOffice integre dans l'offcanvas (docx/xlsx/pdf).
- Upload et analyse d'images (vision optionnelle).
- Generation d'images (API ou fallback local).
- Generation de plots via Python (plot_generate, plot_fred_series).
- plot_fred_series utilise FRED (ex: NASDAQCOM) pour series temporelles sans rate-limit.
- Web search via Brave Web Search API.
- Tool calling (MCP style) via LiteLLM pour declencher automatiquement les outils.
- Drag and drop de fichiers dans la zone de saisie.
- Mode sombre et web tools auto (pas de switch manuel).
- Les documents et images sont scopes par conversation (RAG isole par discussion).
- Streaming token par token dans l'interface (LLM_STREAMING=true).
- Prompt systeme editable et memoire globale partagee entre conversations.
- Sources web cliquables avec preview dans un panneau a droite (onglets Sources/Fichiers).
- PDF viewer avec surlignage (highlight) qui met a jour le fichier et le RAG.
  - Word: append + find/replace pour eviter de casser le formatage.
  - Excel: selection multi-cellules + bouton "Envoyer la selection au chat".

## Reglages assistant (UI)

Via l'icone `SYS` a droite de Conversations:
- Modifier le prompt systeme (sauvegarde immediate).
- Voir/editer la memoire globale appliquee aux futures conversations.
- Supprimer une conversation.

## Commandes (chat)

Utiliser des commandes slash dans la zone de chat:

```
/help
/excel create report.xlsx Sheet1
/excel add-sheet report.xlsx Data
/excel set report.xlsx Sheet1 A1 "Bonjour"
/word create notes.docx
/word append notes.docx "Une nouvelle ligne"
/word replace notes.docx old new
/img create scene.png "A desert sunrise"
/web latest AI news
/doc list
/rag rebuild
```

## Dossiers importants

- `${JACQUES_DATA_DIR:-~/.jacques}/jacques.db`: base SQLite
- `${JACQUES_DATA_DIR:-~/.jacques}/uploads`: documents ingeres
- `${JACQUES_DATA_DIR:-~/.jacques}/exports`: reserve (legacy)
- `${JACQUES_DATA_DIR:-~/.jacques}/images`: images importees
- `${JACQUES_DATA_DIR:-~/.jacques}/generated`: images generees

Par defaut, les donnees (memoire, documents, images) sont stockees dans `~/.jacques`.
Pour reutiliser un dossier local au repo, definir `JACQUES_DATA_DIR=./data` dans `.env`.

## Notes

- Le web search est volontairement simple. Pour un usage pro, brancher un moteur de recherche.
- Le RAG est TF-IDF local. Remplacez par un vecteur store si besoin.
- Les modeles par defaut sont parametres pour les IDs demandes. Ajuster les IDs si votre provider Groq n'expose pas ces noms.
