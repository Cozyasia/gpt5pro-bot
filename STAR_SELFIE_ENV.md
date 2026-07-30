# Star Selfie environment

The feature is isolated and disabled by default.

## Required to enable

```env
STAR_SELFIE_ENABLED=true
GEMINI_API_KEY=...
STAR_SELFIE_FACE_SWAP_URL=https://provider.example/v1/face-swap
STAR_SELFIE_FACE_SWAP_API_KEY=...
```

## Optional

```env
STAR_SELFIE_GEMINI_MODEL=gemini-3.1-flash-image
STAR_SELFIE_GEMINI_API_BASE=https://generativelanguage.googleapis.com/v1/models
STAR_SELFIE_FACE_SWAP_PROVIDER=generic_rest
STAR_SELFIE_FACE_SWAP_RESULT_PATH=data.image
STAR_SELFIE_FACE_SWAP_AUTH_HEADER=Authorization
STAR_SELFIE_FACE_SWAP_AUTH_SCHEME=Bearer
STAR_SELFIE_DATA_ROOT=/data/star_selfie
STAR_SELFIE_SEED_CATALOG=assets/star_selfie/catalog.json
STAR_SELFIE_TIMEOUT_S=600
STAR_SELFIE_MAX_ATTEMPTS=2
```

The generic Face Swap endpoint receives JSON fields `source_image`, `target_image` and `swap_mode`. Images are data URLs. The configured result path may point to a base64 string, data URL, or downloadable HTTPS URL.

Do not enable the feature until the provider endpoint and its exact response path have been verified in staging.
