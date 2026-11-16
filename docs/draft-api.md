# Draft API

`POST /drafts/{post_id}` writes a Swedish article draft and a LinkedIn post
for a topic that Kisslo has chosen in Telegram and given his angle on
(issue #30). n8n calls it after the angle is saved in `posts`; the endpoint
writes the draft, reviews it, saves it as a new version and returns a short
preview that n8n can send to Telegram. Decided at standup 13 Nov: the
generation runs in Python and n8n only calls the endpoint.

```text
Telegram (Kisslo)     n8n (Turker)                 draft API (this file)
Skriv + angle  --->   posts: angle_received  --->  POST /drafts/{post_id}
                                                   1. read post, topic, top articles
                                                   2. Claude call 1: write
                                                   3. Claude call 2: review
                                                   4. save version in post_drafts,
                                                      posts.status = draft_generated
Kisslo reads   <---   sends preview          <---  returns texts + preview
```

The endpoint lives in `src/draft_api.py` and is part of the same FastAPI app
as `GET /telegram/top` (`src/telegram_api.py`), with the same API key check.
The text is written by `src/draft_article.py` and saved by
`src/draft_store.py`.

## Request

```http
POST /drafts/{post_id}
X-API-Key: <TELEGRAM_API_KEY>
Content-Type: application/json

{"stance": "agree"}
```

| Part | Required | Meaning |
|---|---|---|
| `post_id` | yes | `posts.id`, a positive whole number |
| body `stance` | no | `agree` (default) or `rebut`. Where Kisslo's stance is stored is not decided yet, so n8n can send it here. Other fields are refused (422) |
| `?dry_run=true` | no | Check the post and return the prompt and an estimated cost. No call to Claude, nothing is saved |

A draft can be written when the post has status `angle_received`,
`draft_generated` or `changes_requested`. Each call writes a new version;
earlier versions are kept.

What the endpoint reads:

- `posts`: `id`, `topic_id`, `status`, `kisslo_angle`
- the topic's `label` and `why_relevant_sv` (`topic_overview`) and its top
  three articles with title, publication, link and description
  (`topic_top_articles`), the same as `GET /telegram/top`

## What happens in one call

1. **Checks before any cost.** The post must exist and have an allowed
   status, the topic must have a label and articles, and the angle must not
   be empty or longer than 2,000 characters. With Supabase the endpoint also
   checks that the drafts table can be read. A second request for a post
   that is already being written is refused (for example a double click).
2. **Call 1, write.** Kisslo's angle is the core of the article and the news
   are examples. The prompt contains Kisslo's style guide (no contrast
   phrasing, no consultant buzzwords, no repetition, Swedish SME angle),
   prompt v3 from #5 and the rules for sources: only the given articles may
   be linked, and every factual claim the sources do not support, including
   figures, times and costs, is tagged `[UNVERIFIED]`. The article is written
   as Novatech and never names Kisslo; the LinkedIn post is written as him.
3. **Call 2, review.** The same style guide again. The review only removes
   AI-sounding phrasing, repetition and sentences about the sources or the
   writing. It must not add facts, figures, links or length.
4. **Guard.** The code compares the text before and after the review. If the
   review changed a link, the source list, a heading, an `[UNVERIFIED]` tag
   or the `[LÄNK]` placeholder, added a figure, or made the text more than
   5 % longer, the text from call 1 is kept for that part and a warning is
   added. The article and the LinkedIn post are checked separately.
5. **Checks.** Length (500–800 words), 3–4 sections, a headline, 3–5
   LinkedIn sentences, the `[LÄNK]` placeholder, links only to the given
   sources, no reviewer notes and no "Kisslo" in the texts. Problems become
   warnings; they do not stop the draft.
6. **Save.** One new row in `post_drafts`, then `posts.status =
   draft_generated` (only if the status still allows it).

The reviewer notes (Claude's notes, what the review changed, the warnings,
the model and the cost) are stored in their own column and are never part
of the article or the LinkedIn text.

## Response

Example from `tests/fixtures/sample_posts.json` (shortened):

```json
{
  "dry_run": false,
  "source": "fixture",
  "post_id": 1,
  "topic_id": 101,
  "draft_id": null,
  "version": 3,
  "status": "draft_generated",
  "stance": "agree",
  "reviewed": true,
  "stats": {"words": 531, "sections": 4, "linkedin_sentences": 4, "unverified": 0},
  "warnings": [],
  "cost_usd": 0.0546,
  "preview": {
    "text": "<b>Utkast v3: Skriv ner var ni använder AI innan reglerna är klara</b>\n\nMånga småföretag i Sverige väntar …\n\n<b>LinkedIn</b>\nMånga småföretag väntar …\n\nOrd: 531 · Avsnitt: 4 · [UNVERIFIED]: 0 · Varningar: 0",
    "parse_mode": "HTML",
    "buttons": [
      {"text": "Publicera", "callback_data": "publish:1:3"},
      {"text": "Ändra", "callback_data": "revise:1:3"},
      {"text": "Skippa", "callback_data": "keep:1:3"}
    ]
  },
  "article": "# Skriv ner var ni använder AI innan reglerna är klara\n\n…\n\n## Källor\n- …",
  "linkedin": "Många småföretag väntar … \n\nLäs mer: [LÄNK]",
  "reviewer_notes": "# Notes for reviewer (never published)\n\n## Automatic checks\n…",
  "source_news_ids": [1001, 1002, 1003]
}
```

| Field | Meaning |
|---|---|
| `draft_id` | `post_drafts.id`; `null` with the fixture source |
| `version` | Version number for this post, 1, 2, 3 … |
| `status` | Always `draft_generated` on success |
| `reviewed` | `false` if the review call failed; the text is then from call 1 and a warning says so |
| `stats.unverified` | Number of `[UNVERIFIED]` tags. They must be resolved before approval |
| `warnings` | Results of the checks. A draft with warnings is still saved |
| `cost_usd` | Real cost of both calls |
| `preview` | Short Telegram message (HTML): headline, intro, LinkedIn text and the numbers. The whole article does not fit in one Telegram message (4,096 characters) |
| `preview.buttons` | Three buttons: **Publicera** `publish:<post_id>:<version>`, **Ändra** `revise:<post_id>:<version>`, **Skippa** `keep:<post_id>:<version>` (see below) |
| `article`, `linkedin` | Full texts in Markdown. `[LÄNK]` is replaced with the article's link when it is published |
| `reviewer_notes` | For Kisslo, never published |

With `?dry_run=true` the response has `dry_run: true`, `model`, the full
`prompt` for call 1 and an `estimate`
(`input_tokens`, `max_output_tokens`, `max_cost_usd`).

### Errors

On every error no draft is saved by this call and the post keeps its status.

| Status | When | Body |
|---|---|---|
| 401 | `X-API-Key` missing or wrong | `{"detail": "Invalid or missing API key"}` |
| 404 | No post with this id | `{"detail": "Post not found"}` |
| 409 | The post's status does not allow a draft, the topic has no label or articles, the angle is empty or too long, or a draft is already being written for the post | A message that says which |
| 422 | Invalid body (unknown `stance` or field) or `post_id` | FastAPI validation message |
| 502 | Supabase could not be read or written, the drafts table is missing, or Claude failed | `{"detail": "..."}`, details only in the server log |
| 503 | `TELEGRAM_API_KEY` missing or too short on the server | `{"detail": "API key is not configured"}` |
| 500 | `TELEGRAM_SOURCE` is not `fixture` or `supabase` | `{"detail": "Server is not configured"}` |

One case is reported but cannot be rolled back: if the draft row is saved but
the status cannot be changed (because it changed in the meantime), the
response is 502 and the server log says which version was saved. A new call
creates the next version.

## Buttons under the draft

Decided 16 Nov: Kisslo gets three buttons under each draft in Telegram.
The API only returns them; n8n sends them and handles the presses.

| Button | `callback_data` | What happens | Status |
|---|---|---|---|
| Publicera | `publish:<post_id>:<version>` | This version is published on the website | WordPress publishing, separate issue |
| Ändra | `revise:<post_id>:<version>` | Kisslo writes what he wants changed, and a new version is made from this one and his text | Separate issue after #30 |
| Skippa | `keep:<post_id>:<version>` | The draft is kept in `post_drafts` (it is already paid for); nothing more happens | Status value to agree on in #60 (proposal `draft_kept`) |

The version is part of `callback_data`, so a press always applies to the
exact version Kisslo read, also if a newer version exists. The prefixes
differ from `write` / `skip` for topics, so n8n can tell a topic from a
draft. `callback_data` is at most 64 bytes, as Telegram requires.

## Time and cost

- A real call takes 30–60 seconds (two calls to Claude). Set the timeout of
  the HTTP Request node in n8n to at least 120 seconds.
- The cost is about 0.05 USD per draft with `claude-sonnet-5-5` and effort
  `low` (three test runs on 16 Nov 2026: 0.051–0.055 USD). The dry run shows
  the highest possible cost, about 0.12 USD.
- Always try `?dry_run=true` first.

## Storage

| Source | Posts and topics | Drafts |
|---|---|---|
| `fixture` | `tests/fixtures/sample_posts.json` and `sample_topics.json` | One JSON file per version in `output/drafts/post_<id>_v<n>.json` (ignored by Git). The fixture file is not changed |
| `supabase` | `posts`, `topic_overview`, `topic_top_articles` | One row per version in `post_drafts`, then `posts.status` is updated |

`TELEGRAM_SOURCE` chooses the source for both endpoints.

The `post_drafts` table and the new status values come from the migration in
PR #60 (Nosheen). Until it is run, a call with `TELEGRAM_SOURCE=supabase`
stops with 502 "Drafts cannot be saved" before Claude is called. The code
expects:

- `post_drafts` with `id`, `post_id` (→ `posts.id`), `version`,
  `article_text`, `linkedin_text`, `reviewer_notes`, `source_news_ids`
  (`bigint[]`), `stance` (`agree` / `rebut`) and `created_at`, and a unique
  (`post_id`, `version`)
- `draft_generated` (and later statuses) allowed in `posts.status`
- the backend key may SELECT and INSERT on `post_drafts` and UPDATE
  `posts.status`

Saving is two requests today: insert the draft row, then update the status
with the condition that it still allows a draft. A database function that
does both in one transaction has been requested in PR #60.

Table names can be changed in `.env` with `POSTS_TABLE` and `DRAFTS_TABLE`.

## Run locally

1. Settings in `.env` (see `.env.example`): `TELEGRAM_API_KEY`,
   `TELEGRAM_SOURCE`, `ANTHROPIC_API_KEY`, and for Supabase `SUPABASE_URL`
   and `SUPABASE_KEY`.
2. Start the API:

   ```powershell
   uv run uvicorn telegram_api:app --app-dir src --port 8000
   ```

3. Test it:

   ```powershell
   curl.exe -i -X POST http://127.0.0.1:8000/drafts/1
   curl.exe -X POST -H "X-API-Key: <key>" "http://127.0.0.1:8000/drafts/1?dry_run=true"
   curl.exe -X POST -H "X-API-Key: <key>" "http://127.0.0.1:8000/drafts/1"
   ```

   The first gives 401, the second the prompt and estimate, the third a real
   draft (costs money). With the fixture source, post 1 is ready for a draft,
   post 2 and 4 give 409 and post 3 shows a new version.

The same prompt can be tried without the API:

```powershell
uv run python src/draft_article.py --topic-id 101 --angle "Småföretag ska inte vänta på EU" --dry-run
```

## Settings in n8n

- **HTTP Request node:** `POST https://<name>.ngrok-free.dev/drafts/{{ $json.post_id }}`
  with headers `X-API-Key: <key>` (n8n credential) and
  `ngrok-skip-browser-warning: 1`, body `{"stance": "agree"}` or
  `{"stance": "rebut"}`, timeout at least 120 seconds.
- **Telegram node:** text `{{ $json.preview.text }}`, parse mode HTML, and three inline buttons from `preview.buttons`.
- On 409 or 502, tell Kisslo that the draft could not be written; on 502 a
  new try is safe.

## Out of scope

Handling the button presses (n8n), publishing to WordPress, revising a draft from Kisslo's change request,
searching for more supporting articles or research, pasted links or text,
counterpoints in the top 5 (#55) and the source check with a separate model
(#33).