# Diarization tuning: the measurements behind `config/diarization.py`

The constants in `src/config/diarization.py` each carry a one-line reason. This
is the full record those reasons point to: what was measured, on what audio,
and why the current values won.

## Thread count (`DIARIZATION_NUM_THREADS`)

The segmentation model runs one 10 s window at a time, and un-batched
inference degrades with more threads. Per window on an 8-core machine:
2 threads 79.5 ms, 4 threads 196.3 ms, 8 threads 300.5 ms. Batching is the
real win (4 threads at batch 16: 46.9 ms/window). 4 helps the embedding
extractor, which gets long inputs and does scale: on 300 s of AMI, diarization
went 124.4 s -> 96.6 s with identical DER.

Diarization runs on a thread beside transcription (`core/worker.py`), so the
two compete for cores. On 180 s of audio with ivrit-turbo, each pass alone and
then overlapped:

| ct2 threads | onnx threads | diarize | transcribe | both | vs sequential |
|---|---|---|---|---|---|
| auto | 4 (current) | 26.6 s | 130.3 s | 151.2 s | wins by 4% |
| 3 | 1 | 30.3 s | 136.5 s | 152.5 s | wins by 9% |
| 2 | 2 | 25.2 s | 151.5 s | 210.8 s | loses by 19% |

Letting both sides choose is fastest in absolute terms; the second row's larger
margin comes from a worse sequential baseline. The pairing to avoid is
squeezing ctranslate2 down to 2 threads.

`DIARIZATION_REALTIME_FACTOR` (0.3) was first measured at ~0.29x realtime
alone; overlapped it measures 0.15x (26.6 s for 180 s). 0.3 stays as the
conservative figure: it only pads a pre-run estimate, where over-promising
speed is the worse error.

## Engine (`DIARIZATION_ENGINE`)

- `sherpa`: sherpa-onnx's OfflineSpeakerDiarization end to end.
- `powerset`: our own decode of the same segmentation model
  (`core/powerset_decode.py`), with sherpa's embedding and clustering
  (`core/diarization_powerset.py`).

Sherpa's decode is a fixed operating point (argmax over the 7 powerset
classes). On AMI, every knob it exposes left speaker confusion at ~46.5 s of
155.4 s, and asking for 4 speakers returned 3. Thresholding the per-speaker
marginal recovered speech: 143.4 s -> 150.5 s against a 149.9 s reference at
onset 0.40 (`DIARIZATION_ONSET`; below 0.35 it invents speech, 163.0 s at
0.20). Overlap counting (`DIARIZATION_OVERLAP_COUNT` 1.10) peaks at f1 0.374 on
AMI - the best this model does, not a good score.

AMI ES2004a, first 300 s, 3 speakers:

| engine | time | speakers found | DER | confusion |
|---|---|---|---|---|
| sherpa | 83 s | 2 of 3 | 0.4700 | 47.93 s |
| powerset | 119 s | 3 of 3 | 0.4011 | 34.29 s |

`mp3_test/tesr1.wav`, first 300 s, two-person Hebrew conversation:

| engine | time | spans | median span | overlap | split |
|---|---|---|---|---|---|
| sherpa | 118 s | 46 | 2.06 s | 46.9 s | 66/34 |
| powerset | 151 s | 28 | 5.08 s | 34.2 s | 65/35 |

Inside the powerset engine, on 300 s of AMI at num_speakers=4 (sherpa: DER
0.4646, miss 16.29, false alarm 9.40, confusion 46.51):

| embeddings from | DER | miss | false alarm | confusion |
|---|---|---|---|---|
| clean (non-overlapped) frames only | 0.4085 | 14.36 | 13.43 | 35.68 |
| all active frames | 0.4011 | 14.83 | 13.21 | 34.29 |

Confusion falls by about a quarter, but masking overlap out of the embeddings -
the reason to expect that - is slightly worse than not masking: the gain is
from owning the decode, so `mask_overlap` defaults to False. Both runs found 3
speakers for a requested 4 because the first 300 s of ES2004a only has three
(MEE014 speaks later) - not a merge bug, though `_reconstruct`'s majority rule
can genuinely erase a rarely-resolved speaker.

Fewer, longer spans is the wrong direction for a conversation full of short
interjections. Against the hand-corrected Hebrew reference
(`tests/eval/fixtures/diarization/hebrew_2spk.rttm`), powerset lost outright:
DER 0.6030 vs sherpa's 0.5154 (same 300 s, 2 speakers, same embedding model).
`sherpa` stays the default; one constant reverts it.

## Embedding model (`DIARIZATION_EMBEDDING_MODEL`)

Fixture: `hebrew_2spk.rttm`, first 300 s, two speakers - יאיר and נאור, the
minority speaker at ~30% of talk time, whose recall exposes confusion.

`FastClusteringConfig.threshold` is read but unused when `num_clusters > 0`,
which the app always sets from the GUI: thresholds 0.3 and 0.7 gave
byte-identical output (DER 0.5154, 77 spans). With a known count, the only
levers against confusion are the embedding model and `min_duration_on`.

**Phase 1** - engine=sherpa, num_speakers=2, all from the same sherpa-onnx
`speaker-recongition-models` release (upstream's spelling):

| model | MB | DER | confusion | recall יאיר / נאור |
|---|---|---|---|---|
| campplus_sv_en_voxceleb_16k (previous default) | 28.2 | 0.5154 | 74.98 s | 0.88 / 0.25 |
| campplus_sv_zh_en_16k-common_advanced | 27.0 | 0.5234 | 79.18 s | 0.93 / 0.13 |
| **nemo_en_titanet_large** (winner) | 96.7 | 0.2290 | 4.79 s | 0.92 / 0.91 |
| wespeaker_en_voxceleb_resnet152_LM | 75.5 | 0.5207 | 78.72 s | 0.93 / 0.13 |
| wespeaker_en_voxceleb_resnet293_LM | 109.0 | 0.5224 | 79.26 s | 0.93 / 0.12 |

Every VoxCeleb-family model lands at 75-79 s confusion of 252 s; size,
bilinguality and leaderboard rank did not help. TitaNet-L cuts confusion 94%.
The two ResNets were also 9-24x slower (531 s / 1419 s vs ~50-115 s).

**Phase 2** - titanet and campplus, num_speakers=0 (inferred), threshold 0.3-0.7:
inferring the count fragments two speakers into 11-45 clusters at every
threshold. Best of the grid (titanet @ 0.7, DER 0.5297) is more than double
titanet's pinned-count DER. Pinning num_speakers from the GUI is right.

**Phase 3** - regression check on AMI ES2004a, first 300 s, 3 speakers:

| config | DER | confusion | found |
|---|---|---|---|
| sherpa/campplus baseline | 0.4700 | 47.93 s | 2/3 |
| sherpa/titanet | 0.1919 | 5.35 s | 2/3 |

AMI improves on the same error term, so the gate (better נאור recall on Hebrew,
no AMI regression) is met; the 3.4x size increase is justified by a 94%
confusion cut. Phase 4 (`min_duration_on` sweep) was skipped: confusion no
longer dominated.

**Phase 5** - replication on two more Hebrew recordings, full audio, with RTTM
built from hand-typed .docx transcripts by `tests/eval/docx_to_rttm.py`
(validated against hebrew_2spk's known-good RTTM: confusion reconstructs 99.3%
correct; absolute DER does not, so these are A/B only):

| fixture (partner) | model | DER | confusion | recall partner / נאור |
|---|---|---|---|---|
| hebrew_2spk (יאיר) | campplus | 0.5154 | 74.98 s | 0.88 / 0.25 |
| hebrew_2spk (יאיר) | titanet | 0.2290 | 4.79 s | 0.92 / 0.91 |
| hebrew_avi_naor (אבי) | campplus | 0.4971 | 84.12 s | 0.21 / 0.74 |
| hebrew_avi_naor (אבי) | titanet | 0.2466 | 9.01 s | 0.80 / 0.90 |
| hebrew_alon_naor (אלון) | campplus | 0.7129 | 386.04 s | 0.91 / 0.11 |
| hebrew_alon_naor (אלון) | titanet | 0.3758 | 31.11 s | 0.89 / 0.90 |

The win replicates (confusion -89% and -92%). נאור, across three partners and
three acoustic conditions, has recall 0.91 / 0.90 / 0.90 under titanet and
0.25 / 0.74 / 0.11 under campplus.

Full numbers: `eval_output/hebrew_2spk_diarization_sweep.json` and
`eval_output/hebrew_multi_recording_sweep.json`.

## What the docx-derived fixtures cannot measure

A docx-derived reference holds only what a person typed. Masking the blocks
the aligner could not fully match (the `.uem` beside the RTTM - see
`compute_der`'s `scored` parameter) on hebrew_alon_naor:

| window | false alarm | DER | removed |
|---|---|---|---|
| whole file | 284.59 s -> 186.28 s | 0.3758 -> 0.3688 | 35% |
| first 300 s | 57.27 s -> 46.15 s | 0.3729 -> 0.3658 | 19% |

Measure on the whole file: the holes are spread out, so a short window
understates the correction by nearly half. What survives the mask (186 s) is
speech a typist leaves out - backchannels, laughter, crosstalk.

So judge **confusion and speaker recall** on these fixtures, and **false alarm**
on AMI, whose silence really is silence. A change that seems to improve false
alarm on the Hebrew fixtures has most likely just stopped detecting speech.
