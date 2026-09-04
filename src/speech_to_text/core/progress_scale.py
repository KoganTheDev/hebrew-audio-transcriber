"""
Named boundaries for the transcription progress bar.

The bar's percentage crosses three different coordinate systems on its way
from a faster-whisper callback to the number Qt actually paints, and every
boundary between them used to be a bare integer retyped at each site that
needed it - 15 and 90 alone appeared four times apiece across
core/transcriber.py and core/worker.py, with no single place that would
notice if one of the copies drifted. This module is that single place.

The three systems, outside-in:

1. Transcriber's own absolute scale (core/transcriber.py). What
   load_model()/transcribe() emit directly: loading starts at
   TRANSCRIBER_LOAD_START_PERCENT, "model loaded" (= "transcribing begins")
   is TRANSCRIBER_MODEL_LOADED_PERCENT, transcription ends at
   TRANSCRIBER_TRANSCRIBE_END_PERCENT. This is ALSO what reaches the GUI
   verbatim during model loading: worker.py's model-load phase runs once,
   before the per-file loop, and passes Transcriber's own progress straight
   through unmodified (see run_transcription_process's emit_progress).

2. File-local scale (core/worker.py's _transcribe_one and friends). One
   file's own 0-100, independent of the batch: 0..FILE_LOCAL_TRANSCRIBE_START
   is decoding, FILE_LOCAL_TRANSCRIBE_START..FILE_LOCAL_TRANSCRIBE_END is
   transcription (remapped from Transcriber's own scale, see
   from_transcriber_scale), and the rest up to FILE_LOCAL_MAX is speaker
   identification and Hebrew term correction.

3. Batch-wide scale (core/worker.py's run_transcription_process). What
   actually reaches the GUI's progress bar for everything after model
   loading: 0..BATCH_INIT_PERCENT is process start-up,
   BATCH_TRANSCRIBE_START..BATCH_TRANSCRIBE_END is every file's transcription
   in turn (each file's file-local 0-100 rescaled into its
   duration-weighted slice of this band - see emit_local in worker.py), and
   BATCH_TRANSCRIBE_END..BATCH_COMPLETE_PERCENT is rendering and writing the
   final document.

The *_SPAN constants exist so the two remapping formulas (from_transcriber_
scale in worker.py, and the file's own transcribe-fraction math in
transcriber.py) compute their multiplier from the boundaries above rather
than retyping 75/85/86 as bare numbers that happen to equal the same
subtraction.
"""

# ---------------------------------------------------------------------------
# 1. Transcriber's own absolute scale
# ---------------------------------------------------------------------------
TRANSCRIBER_LOAD_START_PERCENT = 5
TRANSCRIBER_MODEL_LOADED_PERCENT = 15
TRANSCRIBER_TRANSCRIBE_END_PERCENT = 90

TRANSCRIBER_TRANSCRIBE_SPAN = (
    TRANSCRIBER_TRANSCRIBE_END_PERCENT - TRANSCRIBER_MODEL_LOADED_PERCENT
)  # 75

# ---------------------------------------------------------------------------
# 2. File-local scale (one file, 0-100, independent of the batch)
# ---------------------------------------------------------------------------
FILE_LOCAL_TRANSCRIBE_START = 5   # 0-5: decoding / stereo detection
FILE_LOCAL_TRANSCRIBE_END = 90    # 5-90: transcription, remapped from (1)
FILE_LOCAL_MAX = 100              # 90-100: speaker id + Hebrew correction

FILE_LOCAL_TRANSCRIBE_SPAN = FILE_LOCAL_TRANSCRIBE_END - FILE_LOCAL_TRANSCRIBE_START  # 85

# Interior checkpoints within the file-local scale: not band boundaries
# another formula derives its span from, just fixed points on this file's
# own timeline that a status message reports progress at. Named anyway
# (rather than left as bare integers at their call sites) so every number
# that means "this file's own progress" lives in one module, boundary or not.
FILE_LOCAL_ANALYZING_PERCENT = 2       # decoding has started
FILE_LOCAL_SPEAKER_ID_END = 97         # diarization's own sub-band ends here
FILE_LOCAL_SPEAKER_ID_SPAN = FILE_LOCAL_SPEAKER_ID_END - FILE_LOCAL_TRANSCRIBE_END  # 7
FILE_LOCAL_CORRECTING_PERCENT = 98     # Hebrew term correction has started

# ---------------------------------------------------------------------------
# 3. Batch-wide scale (what the GUI's progress bar actually shows)
# ---------------------------------------------------------------------------
BATCH_INIT_PERCENT = 2
BATCH_TRANSCRIBE_START = 12
BATCH_TRANSCRIBE_END = 98
BATCH_FORMATTING_PERCENT = 98   # numerically == BATCH_TRANSCRIBE_END: rendering
                                 # begins exactly where per-file transcription
                                 # left off, it is not a coincidence worth a
                                 # second constant.
BATCH_SAVING_PERCENT = 99
BATCH_COMPLETE_PERCENT = 100

BATCH_TRANSCRIBE_SPAN = BATCH_TRANSCRIBE_END - BATCH_TRANSCRIBE_START  # 86

# ---------------------------------------------------------------------------
# Status-only sentinel
# ---------------------------------------------------------------------------
# gui/threads.py emits this in place of a real percentage for messages that
# describe background activity (e.g. faster-whisper retrying a hard-to-decode
# segment) without a known percentage yet. gui/steps/transcription.py reads
# it as "update the status text, but don't move the bar". Any negative value
# would do; -1 is not itself meaningful, it just has to never collide with a
# real percentage, which is always in 0..100.
STATUS_ONLY_PERCENT = -1
