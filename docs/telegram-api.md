# Telegram API

A small Python API that returns the top ranked topics as ready-to-send
Telegram messages with two buttons, **Skriv** and **Skippa** (issue #42).
n8n calls it, sends the messages to Kisslo and handles the button presses.

```text
label_topics.py --save      telegram_api.py            n8n
(Claude, in advance)  --->  GET /telegram/top  <---  calls the API, sends to
writes labels to topics     reads only, no Claude    Telegram, handles buttons,
                                                     sets status (Turker)
```

The API only reads. It never calls Claude and never writes to Supabase.
Labels are produced in advance with `label_topics.py --save`, so a request
costs nothing and answers quickly.

## Endpoint

```http
GET /telegram/top?n=5
X-API-Key: <TELEGRAM_API_KEY>
```

| Parameter | Default | Allowed | Meaning |
|---|---|---|---|
| `n` | 5 | 1–20 | Number of topics |

Only labelled topics are returned (label, `why_relevant_sv` and
`llm_relevance` set), highest score first.

### Response

Example from `tests/fixtures/sample_topics.json` with `n=1`:

```json
{
  "source": "fixture",
  "requested": 1,
  "count": 1,
  "topics": [
    {
      "topic_id": 101,
      "rank": 1,
      "text": "<b>1. EU ger småföretag vägledning om AI-förordningen</b>\n\nSmå företag får tydligare besked om vilka krav i AI-förordningen som gäller dem, till exempel att tala om när kunder pratar med en chattbot.\n\nKällor: 4 · Artiklar: 7 · AI-relevans: 5/5\n\n• <a href=\"https://example.com/tech/eu-ai-act-guidance-small-business\">EU publishes guidance for small businesses under the AI Act</a> – Example Tech News\n• <a href=\"https://example.com/affarer/ai-forordningen-smaforetag\">Nya regler för AI: det här gäller för småföretag</a> – Exempel Affärer\n• <a href=\"https://example.com/policy/ai-act-chatbot-transparency\">AI Act: transparency rules for chatbots explained</a> – Example Policy Weekly",
      "parse_mode": "HTML",
      "buttons": [
        {"text": "Skriv", "callback_data": "write:101"},
        {"text": "Skippa", "callback_data": "skip:101"}
      ]
    }
  ],
  "skipped": []
}
```

| Field | Meaning |
|---|---|
| `source` | `fixture` or `supabase` (from `TELEGRAM_SOURCE`) |
| `requested`, `count` | Asked for and returned. `count` is lower only when there are not enough valid labelled topics |
| `topics[].text` | Telegram HTML: headline, why it matters, counts, up to 3 links. `&`, `<` and `>` are escaped; at most 4096 characters |
| `topics[].parse_mode` | Always `HTML`; send it with the text |
| `topics[].buttons` | Two buttons. `callback_data` is `write:<topic_id>` or `skip:<topic_id>` (at most 64 bytes) |
| `skipped` | Topics left out because of invalid data, as `{"topic_id", "reason"}`. Useful for monitoring |

A topic with an invalid article (missing title, source or link) is skipped
and reported in `skipped`; the API reads a few extra topics so that this does
not make the answer shorter than `n`.

### Errors

| Status | When | Body |
|---|---|---|
| 401 | `X-API-Key` missing or wrong | `{"detail": "Invalid or missing API key"}` |
| 422 | `n` is not a whole number from 1 to 20 | FastAPI validation message |
| 502 | Supabase could not be read | `{"detail": "Could not read topics"}` (details only in the server log) |
| 503 | `TELEGRAM_API_KEY` missing or shorter than 32 characters on the server | `{"detail": "API key is not configured"}` |
| 500 | `TELEGRAM_SOURCE` is not `fixture` or `supabase` | `{"detail": "Server is not configured"}` |

## Run locally

1. Add the settings to `.env` (see `.env.example`):

   ```text
   TELEGRAM_API_KEY=<long random key>
   TELEGRAM_SOURCE=fixture
   ```

   Create a key:

   ```powershell
   uv run python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```

   With `TELEGRAM_SOURCE=supabase` the API also needs `SUPABASE_URL` and
   `SUPABASE_KEY`, and reads the same views as `label_topics.py`
   (`topic_overview`, `topic_top_articles`).

2. With Supabase: label the top topics first (one Claude call per topic
   without a label; already labelled topics are not paid for again):

   ```powershell
   uv run python src/label_topics.py --source supabase --top 20 --save --dry-run
   uv run python src/label_topics.py --source supabase --top 20 --save
   ```

3. Start the API:

   ```powershell
   uv run uvicorn telegram_api:app --app-dir src --port 8000
   ```

   `.env` is read when the server starts; restart it after changing `.env`.
   uvicorn listens on `127.0.0.1` only, so the API is not reachable from
   the network. Do not use `--host 0.0.0.0`; the tunnel is the only way in.

4. Test it:

   ```powershell
   curl.exe -i http://127.0.0.1:8000/telegram/top
   curl.exe -H "X-API-Key: <key>" "http://127.0.0.1:8000/telegram/top?n=2"
   ```

   The first call gives 401, the second the JSON above.

## Expose it with a tunnel (development and demo)

n8n Cloud cannot reach `127.0.0.1` on a laptop, so during development and
the demo the API is exposed through ngrok. Cloud hosting is decided later
by the team.

The ngrok free plan includes one fixed dev domain
(`<name>.ngrok-free.dev` or `.ngrok-free.app`; use exactly the address on the `Forwarding` line) that stays the same after a restart, so n8n can keep the same URL. Limits on the free plan (checked 4 Nov 2026 in
[ngrok's documentation](https://ngrok.com/docs/pricing-limits/free-plan-limits)):
20,000 HTTP requests and 1 GB data out per month. Check ngrok's terms
before using the free plan beyond development and the demo.

```powershell
ngrok config add-authtoken <token from the ngrok dashboard>   # once
ngrok http 8000                                              # uses the dev domain
```

The tunnel only forwards requests; every request still needs the API key.
Stop it (Ctrl+C) when it is not needed.

## Settings in n8n

- **HTTP Request node:** `GET https://<name>.ngrok-free.dev/telegram/top?n=5`
  with headers `X-API-Key: <key>` (store it as an n8n credential, not in the
  workflow) and `ngrok-skip-browser-warning: 1`. ngrok shows a warning page
  to browsers on the free plan; according to its documentation this does not
  affect API clients, and the header makes sure it never does.
- **Telegram node, per item in `topics`:** text `{{ $json.text }}`,
  parse mode HTML, and two inline buttons from `buttons` (`Skriv` →
  `write:<topic_id>`, `Skippa` → `skip:<topic_id>`).

## Security

- One endpoint. The automatic docs pages (`/docs`, `/redoc`,
  `/openapi.json`) are turned off.
- The key is compared with `secrets.compare_digest`, so it cannot be guessed
  by measuring response times. Without a key in `.env` every request is
  refused (fail closed).
- Keys are never in responses or in the repository. The Supabase key is sent
  only in the `apikey` header, and error details stay in the server log.
- Never share the key in a channel or on GitHub. If it leaks, create a new
  one, restart the API and update the n8n credential.

## Out of scope

n8n workflow, Telegram bot, button handling, status in `topics` and the
`posts` table (Turker); score calculation (Mathias); lifecycle of old or
overlapping topics; cloud hosting. `llm_relevance` is an editorial
assessment only and does not affect the score.