v60 avatar/faceswap/photo-error patch

Replace:
- main.py -> main_v60_avatar_faceswap_fix.py

ENV:
- you can keep env_sample_v59 values; v60 sample copied as env_sample_v60_avatar_faceswap_fix.txt
- important: COMET_IMAGE_EDIT_TIMEOUT_S=600

Included fixes:
1) Talking avatar now asks for voice selection consistently:
   - photo first -> button avatar
   - button avatar first -> photo later
   - text intent with cached portrait
   - caption intent on uploaded image/document
   - if text/script was already provided, it is stored and auto-starts right after voice selection.
2) Face swap with 2+ faces: provider order changed to prefer indexed segmind-v2 first; precise composite is disabled when indexed provider is available, reducing blurred/soft results.
3) Better user-facing errors:
   - photo not recognized -> "Фото не распознано, попробуйте ещё раз"
   - clearer voice download failure message.

Not changed yet in v60:
- photo->music clip 20s + guaranteed music mux inside MP4. Current Kling/Comet channel still effectively returns 5/10 sec and audio support is unreliable. This needs a dedicated 2-stage pipeline (video + music + mux/extend).
