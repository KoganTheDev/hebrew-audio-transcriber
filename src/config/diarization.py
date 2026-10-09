"""Speaker-diarization tuning constants.

Each value is measured; the full record - tables, fixtures, the sweeps that
picked the embedding model and engine - is docs/DIARIZATION_TUNING.md.
"""

import os

# Diarization time as a fraction of audio length, for the pre-run estimate.
# Measures 0.15x overlapped with transcription; 0.3 stays deliberately
# conservative, since over-promising speed is the worse error.
DIARIZATION_REALTIME_FACTOR = 0.3

# sherpa-onnx OfflineSpeakerDiarizationConfig knobs, pinned at its current
# defaults so a sherpa release cannot change behaviour silently.
# min_duration_on drops spans shorter than this - one way a genuine short
# utterance vanishes before word-level attribution sees it.
DIARIZATION_MIN_DURATION_ON = 0.3
# Silence shorter than this is bridged rather than ending a span.
DIARIZATION_MIN_DURATION_OFF = 0.5

# A small constant, not cpu_count(): un-batched segmentation slows with more
# threads, and 4 is where the embedding extractor still gains (AMI 300 s:
# 124.4 s -> 96.6 s). Safe beside transcription's own threads - see the doc.
DIARIZATION_NUM_THREADS = min(4, os.cpu_count() or 1)

# A bare filename: core/diarization.py builds both the local path and the
# download URL from it. TitaNet-L, because every VoxCeleb-family model
# (campplus, WeSpeaker ResNets) left ~75 s of speaker confusion on Hebrew where
# TitaNet left 4.8 s, replicated on three recordings, and AMI improved too.
DIARIZATION_EMBEDDING_MODEL = "nemo_en_titanet_large.onnx"

# FastClustering's merge distance - only used when the speaker count is NOT
# pinned, and the GUI always pins it. Never swept on its own.
DIARIZATION_CLUSTER_THRESHOLD = 0.5

# Stated, not implicit, so a future GPU build of onnxruntime cannot silently
# move diarization to another device.
DIARIZATION_PROVIDER = "cpu"

# --- word-level attribution (core/diarization.py:assign_speakers) ----------
# Unsmoothed, per-word speaker votes all bias toward whoever spoke earlier,
# so one speaker appears to absorb the other's turns.

# A run must be this many words before it may cut a segment: one stray word is
# more often a diarizer boundary error than a real one-word turn.
DIARIZATION_MIN_SPEAKER_RUN_WORDS = 2

# An unlabelled word borrows its nearest neighbour's label only across a gap
# this short. Filling across long silence is what carries one speaker's label
# over the other's turn; no label is the honest failure.
DIARIZATION_MAX_FILL_GAP_SECONDS = 1.5

# A one-word interjection ("כן", "לא") still splits a segment when it is this
# long and the other speaker's span covers this much of it - the diarizer is
# then asserting a speaker, not clipping a boundary.
DIARIZATION_INTERJECTION_MIN_SECONDS = 0.35
DIARIZATION_INTERJECTION_MIN_COVERAGE = 0.8

# --- pipeline choice (core/diarization.py:diarize) --------------------------
# "sherpa" (sherpa-onnx end to end) or "powerset" (our own decode of the same
# segmentation model). Powerset wins on AMI but loses on real Hebrew
# conversation (DER 0.6030 vs 0.5154), producing fewer, longer spans.
DIARIZATION_ENGINE = "sherpa"

# Powerset engine only. Marginal probability above which a speaker counts as
# talking: 0.40 recovers AMI's reference speech almost exactly; below 0.35 it
# invents speech.
DIARIZATION_ONSET = 0.40
# Active speakers, averaged over a moment's windows, for it to count as
# overlap. Best f1 this model reaches on AMI is 0.374 - a weak signal.
DIARIZATION_OVERLAP_COUNT = 1.10
# Clean speech a window's speaker needs before it gets an embedding; less is
# mostly noise, and worse to cluster than to leave to neighbouring windows.
DIARIZATION_EMBED_MIN_CLEAN_SECONDS = 0.5
