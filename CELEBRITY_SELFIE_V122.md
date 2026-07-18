# Celebrity Selfie v122

`celebrity_selfie_v122.py` replaces the legacy name-only AI-selfie route with one production mode: **exact celebrity resemblance**.

## User flow

1. Open **Селфи со знаменитостью**.
2. Use the last user photo or upload a new selfie.
3. Choose:
   - 50 Russian public figures;
   - 50 American public figures;
   - name search in Russian or English;
   - upload 1–4 reference images when the person is not in the catalog.
4. Select a scene or enter a custom scene.
5. The bot sends the user identity image plus 3–4 celebrity identity references to the Gemini/Nano Banana compatible multi-image endpoint.
6. The result includes **Улучшить сходство**, which performs a new refinement pass using the original references and the previous draft.

## Reference library

The repository stores only the catalog and synchronization code. It intentionally does not commit arbitrary web photographs.

At runtime, the library:

- resolves each Wikipedia entry to Wikidata;
- retrieves primary-image and Commons-category identifiers;
- searches Wikimedia Commons;
- accepts only files whose metadata reports CC0, public-domain, CC BY, or CC BY-SA licensing;
- rejects non-free, fair-use, NC, ND and all-rights-reserved files;
- stores 3–4 selected files on the persistent Render disk;
- writes source, author and license data to `attribution.json`.

Default layout:

```text
/data/celebrity_library/
  ru/
    А/
      ru_roman_abramovich/
        meta.json
        attribution.json
        ref_01.jpg
        ref_02.jpg
        ref_03.jpg
        ref_04.jpg
  us/
    P/
      us_brad_pitt/
        ...
```

The first use of a person may take longer while references are downloaded. Subsequent generations use the local persistent cache.

## Commands

- `/diag_celebrity` — catalog and cache statistics.
- `/sync_celebrities` — owner-only background fill of missing reference packs.
- `/sync_celebrities force` — owner-only refresh of all packs.

## Optional environment values

All defaults are production-safe; no new secret is required.

```env
CELEBRITY_LIBRARY_ROOT=/data/celebrity_library
CELEBRITY_LIBRARY_MAX_REFS=4
CELEBRITY_LIBRARY_PREFETCH=1
CELEBRITY_LIBRARY_PREFETCH_LIMIT=100
CELEBRITY_LIBRARY_PREFETCH_DELAY_S=45
CELEBRITY_LIBRARY_PREFETCH_PAUSE_S=1.5
CELEBRITY_SELFIE_SEND_AS_DOCUMENT=1
CELEBRITY_SELFIE_MODEL_ATTEMPTS=3
```

## Safety and disclosure

- Generated results are labelled as AI-created.
- Prompts explicitly prohibit fake documentary, news, political-support and endorsement framing.
- Promotional wording is converted to a neutral public-event encounter.
- Users can upload custom references when a person is absent from the catalog or when they want a different current appearance.
