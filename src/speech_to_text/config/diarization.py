"""Speaker-diarization tuning constants and the AMI measurements behind them."""

import os

# Speaker identification is a second full pass over the audio, on top of
# transcription. Measured at ~0.29x realtime on a 4-core CPU with the
# sherpa-onnx pyannote + campplus models, and scaled by core count where used.
# It is not derived from the Whisper calibration benchmark: different models,
# different compute profile.
DIARIZATION_REALTIME_FACTOR = 0.3

# These two are sherpa-onnx's OfflineSpeakerDiarizationConfig knobs, named
# here so the app states its diarization behaviour explicitly instead of
# inheriting whatever sherpa-onnx happens to default to next release. They are
# deliberately held equal to sherpa's current defaults, so passing them changes
# nothing today; see core/diarization.py:diarize for how they are wired in.
#
# min_duration_on drops any speaker span shorter than this many seconds. It
# is one source of the "no overlap at all" fallback in assign_speakers: a
# genuine but very short utterance can fall entirely below this floor and
# vanish from the span list before word-level attribution ever sees it.
DIARIZATION_MIN_DURATION_ON = 0.3
# min_duration_off is the minimum silence gap required to end a speaker span.
# Shorter gaps are bridged rather than treated as a speaker change.
DIARIZATION_MIN_DURATION_OFF = 0.5

# onnxruntime thread count for both diarization models, set explicitly because
# onnxruntime's own default is not the best choice here.
#
# Deliberately a small constant rather than os.cpu_count(): the segmentation
# model is run one 10s window at a time, and un-batched inference does not
# scale with threads, it degrades. Measured on this 8-core machine, per
# window: 2 threads 79.5ms, 4 threads 196.3ms, 8 threads 300.5ms. The win
# comes from batching (4 threads at batch 16: 46.9ms/window), not from
# handing onnxruntime every core it can see. 4 is the compromise that helps
# the embedding extractor - which IS given long inputs and does scale - while
# staying well clear of the oversubscription cliff: measured end to end on
# 300s of AMI, diarization went 124.4s -> 96.6s with identical DER.
#
# min() so a 2-core machine is not told to use 4.
DIARIZATION_NUM_THREADS = min(4, os.cpu_count() or 1)

# onnxruntime execution provider. "cpu" is stated rather than left implicit
# because the installed onnxruntime here reports only Azure and CPU providers
# - there is no CUDA provider to fall back from, and naming it keeps a future
# GPU build from silently changing which device diarization runs on.
DIARIZATION_PROVIDER = "cpu"

# --- word-level attribution (core/diarization.py:assign_speakers) ----------
#
# These three govern how a per-word speaker vote is smoothed before it is
# allowed to cut a transcript segment in two. Left unsmoothed, all three bias
# the same direction - toward whoever was speaking EARLIER - which makes one
# speaker appear to absorb the other's turns.

# A run of words attributed to one speaker has to be at least this long
# before assign_speakers will cut the segment there. A single stray word
# voting for the other speaker is more often a boundary-rounding error in the
# diarizer than a real one-word turn.
DIARIZATION_MIN_SPEAKER_RUN_WORDS = 2

# A word that overlaps no span at all borrows a label from its nearest
# labelled neighbour in time - but only across a gap this short. Beyond it
# the word keeps no label. Filling across a long silence is precisely the
# mechanism that lets one speaker's label run on over the other's turn, and
# an unattributed word renders without a speaker rather than under the wrong
# one, which is the honest failure.
DIARIZATION_MAX_FILL_GAP_SECONDS = 1.5

# A one-word run normally cannot split a segment (see the run-length floor
# above), which erases genuine short interjections - "כן", "לא", "נכון" -
# by folding them into whoever spoke before. It survives as its own run when
# it is at least this long AND the other speaker's span covers essentially
# all of it (see DIARIZATION_INTERJECTION_MIN_COVERAGE), i.e. when the
# diarizer is not merely clipping a boundary but positively asserting a
# different speaker for the whole word.
DIARIZATION_INTERJECTION_MIN_SECONDS = 0.35
DIARIZATION_INTERJECTION_MIN_COVERAGE = 0.8

# --- which diarization pipeline runs (core/diarization.py:diarize) --------
#
# "sherpa"   - sherpa-onnx's OfflineSpeakerDiarization, start to finish.
# "powerset" - our own decode of the same segmentation model
#              (core/segmentation.py), with sherpa's embedding extractor and
#              clustering underneath (core/diarization_powerset.py).
#
# The reason for owning the middle of the pipeline is that sherpa's decode is
# a fixed operating point - an argmax over the 7 powerset classes - and every
# knob it exposes was measured against the AMI reference without moving the
# dominant error. Speaker confusion sat at ~46.5s of 155.4s of reference
# speech across num_clusters=4, count inference at two thresholds, and
# min_duration disabled; and asking for 4 speakers returned 3, i.e. two
# reference speakers merged into one cluster. Thresholding the per-speaker
# marginal instead recovered speech immediately: 143.4s -> 150.5s against a
# 149.9s reference, at onset 0.40.
#
# MEASURED both ways, and the default stays "sherpa" because the result is
# split rather than one-sided.
#
# On AMI ES2004a, first 300s, asking for the 3 speakers that excerpt actually
# contains, "powerset" is clearly better - and note sherpa MERGES two of them:
#
#     sherpa    83s   2 of 3 speakers   DER 0.4700  conf 47.93
#     powerset 119s   3 of 3 speakers   DER 0.4011  conf 34.29
#
# On mp3_test/tesr1.wav, first 300s, a balanced two-person Hebrew
# conversation - the audio this app is actually for - it goes the other way
# on the thing that matters most here:
#
#     sherpa   118s  46 spans  median span 2.06s  overlap 46.9s  66/34 split
#     powerset 151s  28 spans  median span 5.08s  overlap 34.2s  65/35 split
#
# Fewer, longer spans and less detected overlap is the WRONG direction for a
# conversation full of short interjections, which is the complaint this work
# started from. So "powerset" is opt-in until someone measures it against
# Hebrew audio with real speaker labels - which does not exist yet, and is
# the single thing that would most improve confidence here.
#
# One constant reverts everything, which is why it is a constant and not a
# rewrite.
DIARIZATION_ENGINE = "sherpa"

# Marginal probability above which a local speaker counts as talking, for the
# "powerset" engine only. 0.40 rather than the 0.50 that argmax implies:
# measured on 300s of AMI, 0.50 finds 143.4s of the 149.9s of reference
# speech and 0.40 finds 150.5s - essentially exact - at 0.934 recall and
# 0.930 precision. Below 0.35 it starts inventing speech (163.0s at 0.20).
DIARIZATION_ONSET = 0.40

# How many speakers must be judged active, averaged over the windows covering
# a moment, before it is called overlapped speech. Tuned on AMI at f1 0.374
# (recall 0.388, precision 0.361) - which is the best this model does on that
# audio, not a good score. Overlap detection here is a weak signal and is
# treated as one; see core/diarization_powerset.py.
DIARIZATION_OVERLAP_COUNT = 1.10

# A window's speaker needs at least this much clean, non-overlapped speech
# before an embedding is computed for it. Below this the vector is dominated
# by whatever noise happened to be in a handful of frames, and clustering a
# vector like that is worse than leaving those frames to the neighbouring
# windows that do have a confident opinion.
DIARIZATION_EMBED_MIN_CLEAN_SECONDS = 0.5
