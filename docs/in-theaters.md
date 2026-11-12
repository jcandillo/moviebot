# In Theaters builder

Builds an `in_theaters` JSON payload from public theater listing pages for the owner's **first-rate** theaters.
Useful on its own; publishing onto a frame display is optional (`integrations/photo-frame/`).

## Config

Copy `config/local.example.json` to `config/local.json` and list your branches:

- `id` — showtimes.com theater page slug (path segment under `/movie-theaters/`)
- `name` — display name (the label you are willing to show on your private display)
- `city` — city label shown on the card
- `chain` — chain or operator name (public examples use national chains only: AMC, Cinemark, Regal, Alamo Drafthouse)

`config/local.json` is gitignored.

## Build

```bash
python3 theaters/local_showtimes.py build --out /tmp/in_theaters.json
```

Default output is **titles-only**: title, description, theater names, listed/check dates, source provenance. No session times, formats, or counts.

## Publish

On the frame host, under the workflow lease, one CAS:

```bash
# Optional — only if you use the photo-frame integration:
python3 integrations/photo-frame/publish-picks.py set-theaters --expected-revision R --theaters-file /tmp/in_theaters.json
```

Confirm readback hashes; streaming genres and legacy slots must be unchanged.

## Rules

- Any first-rate theater qualifies; exclude discount or second-rate experiences (independents are not excluded by category)
- Public docs, examples and screenshots stay chain-only (national chains), with no branch, city or area details; your private config may name specific cinemas
- Never invent tomorrow’s showtimes from today’s list
- No home/streaming fields on theater items
- Identity: TMDB exact title + runtime ±6 minutes
