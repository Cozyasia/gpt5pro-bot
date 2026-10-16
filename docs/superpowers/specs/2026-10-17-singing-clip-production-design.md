# Singing Clip Production Design

## Goal

Deliver one vertical 9:16 MP4 for a single photographed performer.  The final
track is the exact selected Suno or user-uploaded source track; no TTS track may
replace it.

## Provider contract

Comet's documented Seedance `POST /v1/videos` transport is used only for
image-reference visual footage.  It is deliberately not sent an invented audio
field.  Each visual segment is then passed with the matching real audio excerpt
to the existing Kling advanced lip-sync endpoint.  A clip with a requested but
unavailable lip-sync interval fails closed.

## Billing and recovery

Suno generation and visual generation are two completed stages.  The song is
charged once after it is stored and offered for review.  After approval, the
Seedance plus Kling stage is charged separately.  Seedance task ids, base scenes,
lip-sync tasks and completed scenes are checkpointed per user on the persistent
volume; resume polls an existing task before any new billable POST.

## User inputs

The flow accepts a song brief for Suno or a supplied MP3/WAV/M4A/AAC track.  A
custom track is normalized only when needed, is checked against the selected
clip duration, and is never looped in the final mux.
