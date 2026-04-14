# Railway: AI Targeting (OpenAI)

## 1) Migrations

Apply Postgres migrations (once):

- `scripts/migrate_ai_targeting_pg.sql`
- ensure `candidate_features` has new columns (if you created the table earlier): `scripts/migrate_candidate_features_pg.sql`

## 2) Env vars

Set on **worker/cron** (where Telegram + DB access exist):

- `OPENAI_API_KEY`
- `TG_API_ID`, `TG_API_HASH`, `TG_SESSION_STRING`
- `DATABASE_URL`

## 3) One-time run (Railway cron)

1. Create profile in UI (Broadcast → AI таргетинг → Suggest) and note `profile_id`.
2. Temporarily set the `cron` start command to:

```bash
python -m app.targeting_recompute --workspace-id 1 --targeting-profile-id <profile_id> --days 14 --max-messages-per-source 300
```

3. Deploy `cron`, wait for one successful run, then restore the previous cron command.

