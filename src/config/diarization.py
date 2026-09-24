"""Speaker-diarization tuning constants and the AMI measurements behind them."""

import os

# Speaker identification is a second full pass over the audio, on top of
# transcription. Measured at ~0.29x realtime on a 4-core CPU with the
# sherpa-onnx pyannote + campplus models, and scaled by core count where used.
# It is not derived from the Whisper calibration benchmark: different models,
# different compute profile.
#
# Re-measured since, alongside transcription rather than alone: 26.6s for 180s
# of audio, i.e. 0.15x realtime, comfortably better than this constant. The
# 0.3 is kept as the conservative figure it always was - it is only ever used
# to pad a pre-run estimate, where over-promising speed is the worse error.
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
#
# MEASURED AGAINST THE ALTERNATIVES, because diarization no longer runs alone:
# core/worker.py starts it on a thread beside transcription, so the two now
# compete for the same cores and the obvious worry is that this 4 plus
# ctranslate2's own threads oversubscribe a 4-core machine. On 180s of audio
# with ivrit-turbo, timing each pass alone and then both overlapped:
#
#   ct2 threads  onnx threads   diarize  transcribe   both   vs sequential
#   auto         4 (this)          26.6s     130.3s  151.2s   wins by 4%
#   3            1                 30.3s     136.5s  152.5s   wins by 9%
#   2            2                 25.2s     151.5s  210.8s   LOSES by 19%
#
# Leaving both sides to choose is the fastest of the three, and the overlap
# pays in every configuration that does not starve ctranslate2. Splitting the
# budget explicitly only makes the sequential baseline worse, which is what
# makes its larger "wins by" margin look better than it is. So this stays,
# and the pairing to avoid is squeezing ctranslate2 down to 2.
DIARIZATION_NUM_THREADS = min(4, os.cpu_count() or 1)

# Which sherpa-onnx speaker-embedding model computes the vectors that get
# clustered. A bare filename, not a path: core/diarization.py joins it onto
# MODELS_DIR for the local path and onto the release prefix for the download
# URL, both derived from this one constant so a swap here is the only edit
# needed (see core/diarization.py:_embedding_model_path/_embedding_model_url).
# All candidates ship in the same GitHub release - note the upstream tag is
# really spelled "speaker-recongition-models", not a typo to fix here.
#
# nemo_en_titanet_large.onnx (96.7 MB), not the VoxCeleb-trained campplus
# model (28.2 MB) this app shipped with until this was measured. The old
# comment here argued campplus was chosen because "embeddings capture voice
# timbre more than language-specific phonetics", so any VoxCeleb-family
# model would separate two unfamiliar Hebrew voices. That argument had no
# Hebrew data behind it, and measuring it against real Hebrew speaker labels
# (see the results table at the end of this file) showed it was wrong:
# campplus and both WeSpeaker ResNet alternatives from the same release all
# leave Hebrew confusion at 75-79s of 252s - one speaker absorbing most of
# the other's turns. TitaNet-L is the outlier that actually separates the
# two speakers (confusion 4.79s) and was the only candidate that cleared
# the improve-recall-without-regressing-AMI gate. Timbre-vs-phonetics may
# still be true of embeddings in general; it did not predict which specific
# model tells these two people apart, which is the only thing that matters
# here.
DIARIZATION_EMBEDDING_MODEL = "nemo_en_titanet_large.onnx"

# Cosine-distance threshold FastClustering merges two embeddings at, when
# num_clusters is not pinned to an exact count. Embeddings are vectors in the
# campplus model's speaker-embedding space; two windows cluster into one
# speaker when their cosine distance is below this number. NOT YET SWEPT - it
# is only a named constant so a future measurement pass can vary it, not
# because 0.5 has been checked against alternatives. It is suspect for the
# same reason num_clusters=4 was: on AMI ES2004a (see DIARIZATION_ENGINE
# below), asking for 4 speakers by count still returned 3 - the clusterer
# merged two real people even with the count pinned, which is exactly the
# failure this threshold controls when the count is NOT pinned, and there is
# no measurement yet showing it is not also merging people in the pinned case.
DIARIZATION_CLUSTER_THRESHOLD = 0.5

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
#              (core/powerset_decode.py), with sherpa's embedding extractor and
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
# started from. That measurement against Hebrew audio with real speaker
# labels now exists (tests/eval/fixtures/diarization/hebrew_2spk.rttm, hand-
# corrected), and powerset lost it outright: engine=sherpa DER 0.5154 vs
# engine=powerset DER 0.6030 on the same 300s, same num_speakers=2, same
# embedding model (see the results table at the end of this file). "sherpa"
# stays the default on real data, not just on the AMI split decision above.
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

# --- DIARIZATION_EMBEDDING_MODEL sweep (Hebrew fixture, real speaker labels) --
#
# Full numbers in eval_output/hebrew_2spk_diarization_sweep.json. Fixture:
# tests/eval/fixtures/diarization/hebrew_2spk.rttm (hand-corrected), audio
# mp3_test/diarization_test/<same Hebrew recording>, first 300s, two known
# speakers - יאיר and נאור, נאור being the minority speaker at ~30% of talk
# time and the one whose recall exposes confusion.
#
# First, a claim that has to be settled before any of this sweep means
# anything: sherpa_onnx.FastClusteringConfig.threshold is READ but NOT USED
# when num_clusters > 0 (this app always pins a known count from the GUI).
# Verified empirically: engine=sherpa, num_speakers=2, cluster_threshold in
# {0.3, 0.7} produced byte-identical output (DER 0.5154, 77 spans, same
# recall) at both values. So with a known speaker count, this constant does
# nothing, and the only levers against a confusion-dominated error are the
# embedding model and min_duration_on.
#
# Phase 1 - engine=sherpa, num_speakers=2 (pinned), all from the same
# sherpa-onnx speaker-recongition-models release:
#
#     model                                                    MB    DER     conf    recall יאיר/נאור
#     campplus_sv_en_voxceleb_16k (CURRENT, then default)      28.2  0.5154   74.98s  0.88 / 0.25
#     campplus_sv_zh_en_16k-common_advanced (bilingual)        27.0  0.5234   79.18s  0.93 / 0.13
#     nemo_en_titanet_large (WINNER)                           96.7  0.2290    4.79s  0.92 / 0.91
#     wespeaker_en_voxceleb_resnet152_LM                       75.5  0.5207   78.72s  0.93 / 0.13
#     wespeaker_en_voxceleb_resnet293_LM                      109.0  0.5224   79.26s  0.93 / 0.12
#
# All four VoxCeleb-family losers land in the same place - confusion at
# 75-79s of 252s, נאור recall 0.12-0.13, no better than the control they were
# meant to improve on. Being bigger, more bilingual, or higher on the
# VoxCeleb leaderboard did not help; none of that measures separability on
# Hebrew voices specifically. TitaNet-L is the outlier: confusion drops 94%
# and נאור's recall goes from "usually not found" to "usually found". The
# two ResNet losers were also 9-24x slower to run (531s/1419s vs ~50-115s for
# the others) for a worse result - recorded so nobody re-tries them for speed
# reasons either.
#
# Phase 2 - best two by נאור recall (titanet, campplus control), engine=
# sherpa, num_speakers=0 (inferred), threshold swept 0.3-0.7. LOSING
# direction across the board: threshold only matters when the count is
# unknown, and inferring it here fragments two real speakers into 11-45
# clusters at every threshold tried. Best of the whole grid (titanet @ 0.7,
# DER 0.5297) is still more than double titanet's pinned-count DER (0.2290).
# This confirms the app is right to keep pinning num_speakers from the GUI,
# and that the threshold grid was never where the fix could live (per the
# inertness finding above) - full grid in the JSON.
#
# Phase 3 - regression check, winning config against AMI ES2004a (first
# 300s, num_speakers=3, the pre-existing sherpa reference point):
#
#     known sherpa/campplus baseline   DER 0.4700   conf 47.93s   2/3 found
#     sherpa/titanet                   DER 0.1919   conf  5.35s   2/3 found
#
# No regression - AMI improves too, on the same error term. Gate (improve
# נאור recall on Hebrew AND do not regress AMI) is met on both axes, so
# DIARIZATION_EMBEDDING_MODEL's default changed to nemo_en_titanet_large.onnx
# despite the 3.4x size increase (28.2 MB -> 96.7 MB): a 94% confusion
# reduction is not the "rounding error" case size should veto, which is
# exactly why the two other 75+ MB candidates were rejected instead - they
# paid the same size tax and got nothing for it.
#
# Phase 4 (DIARIZATION_MIN_DURATION_ON sweep) was skipped: confusion was the
# dominant error this sweep targeted, and phase 1 alone took it from 74.98s
# to 4.79s on Hebrew and from 47.93s to 5.35s on AMI. The condition for
# running phase 4 - confusion still dominant after the embedding fix - was
# not met.
