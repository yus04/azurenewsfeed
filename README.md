# ☁️ Azure News Feed

A daily-updated Azure blog aggregator hosted on GitHub Pages. Collects articles from Azure blogs and presents them in a clean, searchable interface — last 30 days only.

**Live site:** [azurefeed.news](https://azurefeed.news)

## Features

- 📰 **50 blog sources** — Azure, DevOps, Developer Tools, Data & AI, and more
- 🔍 **Search & filter** — Find articles by keyword, blog category, or date range
- ⭐ **Bookmarks** — Save articles for later (stored locally per browser)
- 🌙 **Dark mode** — Easy on the eyes
- 📱 **Responsive** — Works on desktop, tablet, and mobile
- 🤖 **Auto-updated** — GitHub Actions fetches new articles daily at 7 AM EST (12 PM UTC)
- 📅 **Last 30 days** — Keeps only recent articles for a lean, fast experience
- 🗄️ **Azure Blob Storage export** — Each new article is also saved as an individual JSON file in Azure Blob Storage for downstream processing (e.g. GPT-based summarization/tagging)

## Blog Sources

| Category | Blogs |
|----------|-------|
| **Compute** | Azure Compute, AKS, Azure Virtual Desktop, High Performance Computing |
| **Data & AI** | Analytics on Azure, Azure Databricks, Oracle on Azure, Cosmos DB, Azure SQL, Microsoft Foundry |
| **Infrastructure** | Azure Infrastructure, Azure Arc, Azure Stack, Azure Networking, Azure Storage |
| **Architecture** | Azure Architecture, Customer Innovation, ISE Developer Blog |
| **Apps & Platform** | Apps on Azure, Azure PaaS, Integrations, Messaging, Aspire, Azure SDK |
| **Operations** | Governance & Management, Observability, FinOps, Azure Tools, Migration, Azure DevOps |
| **Community** | Azure Dev Community, Azure Events, Linux & Open Source, All Things Azure, Microsoft Developers Blog, Azure Global Black Belt, Azure Citadel |
| **Developer Tools** | Visual Studio, VS Code, Windows Command Line, Develop from the Cloud |
| **Specialized** | Communication Services, Confidential Computing, Maps, Telecommunications, Planetary Computer |

## Setup

### 1. Create the GitHub repository

```bash
gh repo create azurenewsfeed --public --source=. --remote=origin
```

### 2. Push the code

```bash
git init
git add .
git commit -m "Initial commit - Azure News Feed"
git push -u origin main
```

### 3. Enable GitHub Pages

Go to **Settings → Pages → Source** and select **Deploy from a branch** → **main** → **/ (root)**.

### 4. Trigger the first data fetch

Go to **Actions → Fetch Azure Blog Feeds → Run workflow** to populate the initial data.

### 5. Visit your site

Your feed will be live at `https://azurefeed.news`

## Local Development

To test the feed fetcher locally:

```bash
pip install -r scripts/requirements.txt
python scripts/fetch_feeds.py
```

Then serve the site:

```bash
python -m http.server 8000
```

Open [http://localhost:8000](http://localhost:8000) in your browser.

## Azure Blob Storage Export

In addition to the site data in `data/`, every GitHub Actions run also exports each **new** article as an individual JSON file to Azure Blob Storage, so downstream systems (e.g. a GPT-based Japanese summarization/tagging pipeline) can consume raw article content. This is a purely additive feature — it does not change or remove the existing feed generation, GitHub Pages publishing, or the `data/` files.

### 1. Required Azure Storage configuration

- The target **Storage account** and `raw-articles` **Blob container** must already exist. The uploader does not create containers.
- GitHub Actions signs in with **OIDC and Microsoft Entra ID** using `azure/login@v2`; no storage account key or connection string is used.
- The Entra application/service principal used by the workflow must have a GitHub federated credential for this repository's `master` branch and **Storage Blob Data Contributor** access scoped to the `raw-articles` container. This role allows the workflow to list existing blobs and upload new article blobs.

### 2. Configure GitHub Actions

In your GitHub repository, go to **Settings → Secrets and variables → Actions** and configure:

- **Repository secrets:** `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, and `AZURE_SUBSCRIPTION_ID` for the Entra identity.
- **Repository variable:** `AZURE_STORAGE_ACCOUNT_NAME` for the existing Storage account.

The workflow grants `id-token: write` to request a GitHub OIDC token, logs in to Azure, then uses the Azure CLI credential for Blob Storage access. Missing or invalid identity configuration or insufficient container permissions causes the upload step and workflow to fail.

### 3. Blob path structure

Each article is stored as its own blob, one file per article:

```
raw/articles/YYYY/MM/DD/{id}.json
```

- `YYYY/MM/DD` is the UTC date the article was **collected** (the GitHub Actions run date).
- `{id}` is a stable identifier derived from the article URL: the URL is normalized (lowercased scheme/host, fragment removed, tracking query parameters like `utm_*` stripped, remaining query parameters sorted, trailing slash removed) and then hashed with SHA-256. The same URL always produces the same `id`, which is used to skip re-uploading articles that were already saved in a previous run (no `articles.json`-style aggregate file is written to Blob Storage).

Example path: `raw/articles/2026/09/06/a1b2c3d4....json`

Each JSON file has the shape:

```json
{
  "id": "sha256(url)",
  "title": "What's new in Azure Firewall",
  "source": "Azure Networking Blog",
  "author": "John Doe",
  "publishedAt": "2026-09-04T00:00:00Z",
  "url": "https://...",
  "summary": "...",
  "content": "...",
  "images": ["https://..."],
  "category": "Networking",
  "collectedAt": "2026-09-06T01:00:00Z"
}
```

`author` and `summary` are `null` when not available from the source feed. `category` reuses the existing Azure Feed categories (Compute, Data & AI, Infrastructure, Architecture, Apps & Platform, Operations, Community, Developer Tools, Specialized). `images` only contains image URLs found in the article — images themselves are never downloaded.

### 4. Verifying it works

1. Run the workflow manually via **Actions → Fetch Azure Blog Feeds → Run workflow** and check the upload step's logs.
2. To run locally, install the dependencies, sign in with Azure CLI as an identity that can access the container, and provide the Storage account name:
   ```bash
   pip install -r scripts/requirements.txt
   az login
   export AZURE_STORAGE_ACCOUNT_NAME="<storage-account-name>"
   python scripts/fetch_feeds.py
   AZURE_STORAGE_CONTAINER="raw-articles" python scripts/upload_to_blob.py
   ```
3. Confirm blobs exist at `raw/articles/YYYY/MM/DD/{id}.json` and re-run to verify previously uploaded articles are skipped as duplicates.

## 🎬 Teleprompter - Roteiro Diário para Vídeo

Gera automaticamente um roteiro em **português brasileiro** para gravar vídeos diários de atualizações do Azure — estilo John Savill, mas em PT-BR.

### Como usar

```bash
# Gerar roteiro (requer feeds.json atualizado)
python scripts/generate_teleprompter.py

# Para pegar artigos dos últimos 2 dias
DAYS_BACK=2 python scripts/generate_teleprompter.py
```

O roteiro é salvo em:
- `data/teleprompter/roteiro-YYYY-MM-DD.md` (arquivo datado)
- `data/teleprompter/latest.md` (sempre o mais recente)

### Funcionalidades do roteiro

- ✅ Abertura e encerramento prontos
- ✅ Artigos agrupados por categoria
- ✅ Marcações `[PAUSA]` para ritmo de leitura
- ✅ Frases curtas otimizadas para teleprompter
- ✅ Se `OPENAI_API_KEY` estiver configurada, gera roteiro com IA (mais natural e contextualizado)
- ✅ Sem a API key, gera roteiro estruturado básico (ainda funcional)

### Dica: Apps de teleprompter

Abra o arquivo `latest.md` em qualquer app de teleprompter (ex: PromptSmart, Teleprompter Premium, ou até um browser em tela cheia com scroll automático).

## How It Works

1. **GitHub Actions** runs daily at 7 AM EST / 12 PM UTC (or manually)
2. **Python script** fetches RSS feeds from all 50 Azure and Microsoft developer blogs
3. Articles from the last 30 days are deduplicated, sorted, and saved to `data/feeds.json`
4. **Teleprompter script** generates a daily PT-BR video script from today's articles
5. **New articles are normalized and uploaded to Azure Blob Storage** (one JSON file per article, deduplicated by URL-derived id)
6. The commit triggers **GitHub Pages** to redeploy
7. The **static frontend** loads the JSON and renders the feed

## License

MIT
