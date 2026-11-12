# TMDB API key setup

MovieBot matches titles and pulls spoiler-free overviews through TMDB. Use a **personal Developer key** for your own instance.

## Steps

1. Open [TMDB](https://www.themoviedb.org/) and sign in (Google or email is fine — use **your** account tile, not a household shared account).
2. Complete any verification your account requires (passkey, device prompt, or email link).
3. Request a **Developer / Personal** API key. Name it something like `MovieBot` (instance-local).
4. Save the key only through your agent host's **secure secret entry** (a masked secret prompt, secret manager or OS keychain) as `TMDB_API_KEY`. For local runs, a gitignored `.env` (see `.env.example`) is acceptable; never commit it.
5. Never read the key aloud, paste it into chat, commit it, or put it in skills or docs.

## Rules

- The key must never appear in plain text in the repo, memory, or chat.
- Spec path for where-to-watch: TMDB `movie/{id}/watch/providers` (data supplied to TMDB by JustWatch; keep the attribution). The reference `pipeline/where_to_watch.py` currently parses public JustWatch US pages as a stopgap and needs no key; check JustWatch's terms before relying on it. Treat unknown as `unverified`; never invent offers.
- If setup fails, stop and ask the instance owner; do not scrape credentials from browsers or password managers into git.
