# V265 L2 commercial asset gate

Checkpoint date: 2026-09-09. This is an engineering provenance gate, not legal advice.

## Verdict

FaceVerse V4 remains useful research evidence for the required representation class, but its current asset pack is **not eligible for production integration**. The V4 repository code is MIT; that does not by itself establish commercial rights to the separately downloaded PCA model or pretrained regressor.

| Component | Primary evidence | Commercial/server/redistribution verdict |
|---|---|---|
| FaceVerse V4 code | `LizhenWangT/FaceVerse_v4` LICENSE, MIT | Code only: yes, subject to MIT |
| `faceverse_v4_2.npy` | Separate OneDrive download; no asset-specific grant found | Unclear; blocked |
| FaceVerse ResNet50 regressor | Separate download; README says trained with FaceVerse rendering data and FFHQ | No complete commercial provenance; blocked |
| FaceVerse dataset-derived assets | Dataset agreement says non-commercial research only and prohibits commercial products/services | No |
| FFHQ-derived regressor training | FFHQ dataset is CC BY-NC-SA 4.0 and includes BY-NC images | No clear commercial grant |
| ONNX mirror | Mirror code says MIT, but identifies itself as an implementation of upstream FaceVerse V4 | Does not establish upstream asset rights |
| Current face parsing code | `yakhyo/face-parsing` code is MIT | Code only: yes |
| Current parsing weights | README says trained on CelebAMask-HQ | No: dataset/software terms are non-commercial |

Primary URLs:

- https://github.com/LizhenWangT/FaceVerse_v4/blob/master/LICENSE
- https://github.com/LizhenWangT/FaceVerse_v4/blob/master/README.md
- https://github.com/LizhenWangT/FaceVerse-Dataset/blob/main/README.md
- https://github.com/NVlabs/ffhq-dataset/blob/master/LICENSE.txt
- https://github.com/yakhyo/face-parsing/blob/main/README.md
- https://github.com/switchablenorms/CelebAMask-HQ/blob/master/README.md

## Enforced consequence

- Production, server-side inference, redistribution and unattended CI use are fail-closed.
- `scripts.v265_l2_prepare` now refuses to download the pack unless a human explicitly supplies `--allow-research-assets` for local research.
- CI verifies refusal and no longer downloads or executes these assets.
- Existing geometry reports remain a historical negative research checkpoint; they are not production qualification.
- FaceVerse expression-orthogonal residual, constrained case06 fitting, case08 work and renderer integration stop here unless the rights holder supplies an explicit commercial agreement covering model assets, pretrained weights, training-derived use, server inference and deployment/redistribution.

## Closest commercially-clear direction

MediaPipe code and canonical face topology are Apache-2.0 and provide dense landmarks, pose transforms and blendshape outputs. They are a clear foundation for pose/expression tracking, but they do **not** provide the rich intrinsic identity basis that FaceVerse demonstrated is required. Therefore MediaPipe alone is not promoted as L2. The replacement must combine this clear tracking/topology layer with a commercially licensed or internally trained identity model and canonical 3D residual; its training datasets and weights need an asset-level provenance manifest before benchmark integration.

## Status carried forward

Because the first mandatory gate failed, no new cross-view, case06, case07, case08, render or memory qualification is claimed in this checkpoint. Prior measurements remain negative: case06 invalid, case08 not disentangled, parsing not production-clear, and standalone peak RSS 596892 KiB exceeds 512 MiB. A 2 GiB tier is the provisional safe experimental target for the eventual replacement until end-to-end lifecycle measurements establish a lower tier.
