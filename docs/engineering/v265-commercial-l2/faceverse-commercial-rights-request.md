# FaceVerse commercial-rights request manifest

Send this request to the contacts published by the FaceVerse authors: Lizhen Wang (`wanglz@126.com` in V4; `wanglz14@126.com` in the original repository), Zhiyuan Chen (`juzhen.czy@antfin.com`), and Yebin Liu (`liuyebin@mail.tsinghua.edu.cn`). No public self-service commercial license route was found.

## Assets that must be named in the agreement

1. `faceverse_v4_2.npy`, including mean shape, identity, expression and texture/PCA bases, topology, masks and derived subsets.
2. FaceVerse V4 ResNet50 pretrained checkpoint and any authorized FP16/INT8/ONNX conversion.
3. Every FaceVerse V4/V3 model/PCA asset required to reconstruct or render the face.
4. Components derived from the FaceVerse rendering/scan/RGB-D datasets.
5. Components trained on or derived from FFHQ, including the V4 regressor.

The agreement must not merely license repository code or grant dataset access. It must explicitly identify the pretrained weights and model assets by filename/version/hash or an exhaustive schedule.

## Required written grants

For every scheduled asset, request an explicit, worldwide grant for:

- commercial products and commercial services;
- a paid SaaS and paid Telegram bot;
- server-side, unattended production inference;
- processing photographs uploaded by users;
- deployment of weights on private company-controlled servers;
- storage inside private containers, images, artifact registries and backups;
- unattended CI/CD download, conversion, testing and deployment;
- modification, pruning, quantization, optimization and ONNX conversion;
- creation and commercial use of derivative models/assets, including face-only topology packs and canonical residual representations;
- production use without an academic/research-only restriction;
- permitted number of users, monthly active users, requests, servers and territories, or an express statement that these are unlimited;
- term, renewal, termination, reporting, audit and fee conditions;
- continued operation and deletion obligations after termination.

Redistribution to end users is **not required** for the current server-only architecture. The agreement must nevertheless permit internal copying among private build systems, registries, servers, backups and contractors/processors. If a container is ever delivered to a third-party hosting provider, that private deployment must not be treated as prohibited redistribution.

## Provenance warranty required

The licensor must represent and warrant that it owns or controls sufficient rights to license the pretrained weights and all scheduled assets for these uses, including despite FaceVerse dataset-derived and FFHQ-derived training provenance. Request disclosure of any third-party terms, attribution, privacy/biometric restrictions and downstream obligations. A general MIT/BSD code reference is not sufficient.

## Suggested short request

> We are evaluating FaceVerse V4 for a paid server-side photo-processing service and Telegram bot. Please provide commercial license terms specifically covering `faceverse_v4_2.npy`, the V4 ResNet50 pretrained weights, all required PCA/model assets, and authorized ONNX/quantized derivatives. We need worldwide server inference, user-photo processing, private server/container storage, unattended CI/CD, modification/optimization, and internal deployment rights. We do not distribute weights to end users. Please confirm that you have authority to license the pretrained weights and derived assets notwithstanding FaceVerse-dataset and FFHQ training provenance, and identify any user/request limits, fees, term, attribution, privacy, audit, hosting-provider, and termination conditions.

No FaceVerse production integration resumes until the executed terms and asset schedule have been reviewed and recorded.
