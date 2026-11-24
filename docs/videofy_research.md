# Videofy Integration Research (#63)

## Overview
[Videofy Minimal](https://github.com/schibsted/videofy_minimal) is Schibsted's open-source article-to-video pipeline. It converts structured article data into narrated vertical (`9:16`) and horizontal (`16:9`) MP4 videos using an LLM for scriptwriting/media matching, ElevenLabs for text-to-speech, and Remotion for rendering.

---

## Findings

### 1. Inputs, API & Self-Hosting
* **Self-Hosting in Docker:** Supported out of the box via Docker Compose (`docker compose up --build`), running a Next.js frontend (`:3000`) and a Python FastAPI backend (`:8001`). Project state is stored on the local filesystem under `projects/<id>/` (`input/`, `working/`, `output/`).
* **Input & Fetcher Plugins:** Content is ingested via pluggable Python fetchers (`fetchers/<name>/fetcher.json` + `fetcher.py`) that normalize data into `projects/<id>/input/article.json` alongside downloaded `images/` and `videos/`. Built-in plugins include `reuters`, `ap`, and a generic `web` scraper for testing, while custom CMS/API sources are added as custom fetcher plugins.
* **Manuscript Format & API Flow:** The FastAPI service (`:8001`) orchestrates fetching, generates an editable JSON script (`working/manuscript.json`), synthesizes audio, and compiles `output/processed_manuscript.json` before rendering final MP4s.

### 2. Authentication & Credentials
* **Environment Variables (`.env`):** Authentication to external AI providers is handled strictly via local environment variables—no credentials are stored in the repository.
* **Required Credentials:**
  * `OPENAI_API_KEY` (manuscript generation and visual media matching)
  * `ELEVENLABS_API_KEY` (voiceover synthesis)
  * *(Optional)* Reuters or AP API credentials if using those built-in fetchers.
* **Access Control:** Videofy Minimal has no built-in user login or token auth on its web UI or FastAPI endpoints, so it must run on an isolated internal Docker network rather than being exposed publicly.

### 3. Video Delivery & Storage (Target: Cloudflare R2)
* **Default Output:** Rendered MP4 files (`render-vertical.mp4`, `render-horizontal.mp4`) are written to `projects/<id>/output/` on the mounted Docker volume.
* **Cloudflare R2 Integration:** Because Cloudflare R2 is S3-compatible and has zero egress fees, our pipeline can upload the rendered MP4 straight from `projects/<id>/output/` to R2 using Python (`boto3`) with `R2_ENDPOINT_URL`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, and `R2_BUCKET_NAME` in `.env`, then persist the resulting public/custom-domain URL on the post record.

### 4. Customer / Brand Configuration
Customer profiles are defined as standalone JSON files in `brands/<brand_id>.json` (copied from `brands/default.json`) and selected per project:
* **Visual Branding:** Overlay `logo`, motion bumpers (`intro`, `wipe`, `outro`), color palettes, visual theme, and default aspect ratios.
* **Voice Settings:** Default ElevenLabs voice ID and TTS parameters (stability, similarity, style).
* **AI Instructions & Models:** Custom editorial prompts controlling script tone/structure and explicit OpenAI model assignments (`manuscriptModel` and `mediaModel`).

### 5. Licenses & Costs
* **Videofy Minimal (`schibsted/videofy_minimal`):** **Apache-2.0 License** ($0 software cost) ([Source](https://github.com/schibsted/videofy_minimal)).
* **Remotion (Bundled Video Renderer):** Videofy Minimal relies on Remotion (`player/`) for video composition and rendering ([Remotion License & Pricing](https://www.remotion.dev/docs/license/pricing)):
  * **Free ($0):** Individuals, non-profits, and companies with **3 or fewer people** total headcount (commercial and automated use allowed).
  * **Paid Company License (4+ people):** Required for commercial/production use—either **Remotion for Automators** at **$0.01/render ($100/month minimum)** for automated pipelines, or **Remotion for Creators** at **$25/month per seat**.
* **Usage & Infrastructure Costs:**
  * **OpenAI & ElevenLabs APIs:** Pay-as-you-go token and character billing (typically a few cents per short video).
  * **Hosting & Storage:** Self-hosted Docker VPS compute + Cloudflare R2 storage (~$0.015/GB-month after 10 GB free tier, $0 egress).

---

## Integration Recommendation (For Upcoming Video Cards)

1. **Deploy Videofy as an Internal Docker Service:** Run `videofy_minimal` via `docker compose` on the same private network as our existing pipeline (`http://videofy:8001`), mounting shared volumes for `projects/` and `brands/` and injecting secrets via a single gitignored `.env` file.
2. **Implement Delivery in Python (Rather Than n8n):** Add a dedicated Python client/step after the `write-and-publish` step. Python integrates directly with our `posts` workflow, guarantees explicit error reporting (raising exceptions on failure rather than silently skipping), and allows clean `pytest` unit tests using fake HTTP/S3 responses with zero live calls.
3. **Trigger on `posts` Approved Status:** Trigger video generation when a post reaches `approved` status in `posts` rather than coupling directly to the Telegram webhook, allowing failed renders or uploads to be retried cleanly from post state.
4. **Pipeline Execution Flow:**
   1. Read the approved post and customer brand ID from `posts`.
   2. Pass the article payload to Videofy (via a custom `internal_posts` fetcher or direct `input/article.json` + FastAPI `:8001` trigger).
   3. Upload the rendered MP4 from `projects/<id>/output/` to Cloudflare R2 via `boto3`.
   4. Store the returned R2 video URL on the `posts` record for downstream captioning and publishing steps.