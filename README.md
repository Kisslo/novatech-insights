# novatech-insights
Ett system för att skapa och förädla content till olika plattformar
  ## News Collection

Run the collector from the repository root:

```powershell
uv run python src/collect_news.py
```

Sources are configured in `data/sources.csv`.
Results are saved to `data/news.csv`.

- Supports RSS feeds with `channel/item` elements.
- Prevents duplicates by checking the exact article link.
- Stores publication dates in ISO 8601 format in UTC,
  for example `2026-10-15T09:30:00Z`.
- Keeps only articles published within the last seven days.
- Skips articles with missing, invalid, timezone-free,
  or future publication dates.
- Applies the same checks to previously saved articles.
- Saves articles with the newest first.

Change `MAX_AGE_DAYS` in `src/collect_news.py` to adjust
the time window.

Output columns: `title`, `link`, `source`, `published`, `subject`.

The `subject` field is currently left blank for new articles.
RSS descriptions and full article text are not collected.