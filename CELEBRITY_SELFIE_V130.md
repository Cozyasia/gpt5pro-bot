# Celebrity Selfie v130 — identity-lock production pipeline

## Product scope

The Telegram button remains **«Селфи со звездой»**. The built-in catalog is intentionally limited to:

- 20 Russian public figures;
- 10 American public figures.

A smaller curated catalog is preferred over a large unstable list. Users can still upload custom celebrity references when necessary.

## Quality pipeline

1. **Selfie preflight**
   - verifies resolution, brightness, contrast and sharpness;
   - uses the existing runtime face detector when available;
   - rejects zero faces or multiple faces;
   - does not accept an unusable input merely to complete the flow.

2. **Scene draft**
   - Gemini/Comet creates the background, lighting, body composition and selfie framing;
   - prompt enforces exactly two foreground people;
   - user is positioned left, celebrity right, with equal-size upright faces;
   - background faces must remain distant and unrecognisable.

3. **Mandatory identity lock**
   - PiAPI `Qubico/image-toolkit` / `multi-face-swap` receives a two-person identity source sheet;
   - source index `0` is the user and source index `1` is the selected celebrity;
   - target indices `0,1` are mapped to the stable left/right draft layout;
   - raw Gemini drafts are never delivered if this step fails.

4. **Improve resemblance**
   - does not regenerate the scene;
   - re-applies the original two identities to the previous result;
   - therefore preserves location, clothing and composition.

## Important product guarantee

No image system can honestly guarantee a numeric 99% match in every pose and lighting condition. v130 instead implements a fail-closed quality contract: a weak raw scene is not labelled or sent as a finished exact selfie when the identity-lock stage fails.

## Required provider

`PIAPI_API_KEY` must be present in Render. The project already declares this secret variable for its FaceSwap functions.

## Optional environment values

```env
CELEBRITY_IDENTITY_LOCK_REQUIRED=1
CELEBRITY_IDENTITY_ATTEMPTS=2
CELEBRITY_IDENTITY_TIMEOUT_S=300
CELEBRITY_IDENTITY_POLL_S=2.5
CELEBRITY_SELFIE_MIN_SIDE=512
CELEBRITY_SELFIE_MIN_CONTRAST=14
CELEBRITY_SELFIE_MIN_SHARPNESS=18
```

## Diagnostics

`/diag_celebrity_flow` reports:

- catalog size `30 (ru=20, us=10)`;
- selfie preflight enabled;
- Gemini scene + PiAPI identity-lock pipeline;
- face-only refinement;
- raw draft delivery blocked.
