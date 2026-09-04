"""Named boundaries for the transcription progress bar.

One percentage crosses three coordinate systems on its way from a
faster-whisper callback to the number Qt paints, and 15 and 90 alone appeared
four times apiece across transcriber.py and worker.py. This is the one place
they live, so a boundary cannot drift between copies.

1. Transcriber's absolute scale (core/transcriber.py). What load_model() and
   transcribe() emit directly, and what reaches the GUI verbatim during model
   loading - worker.py's model-load phase passes it straight through.
2. File-local scale (core/worker.py's _transcribe_one). One file's own 0-100,
   independent of the batch: decoding, then transcription remapped from (1),
   then speaker identification and Hebrew term correction.
3. Batch-wide scale (core/worker.py's run_transcription_process). What the
   GUI's bar shows after model loading: each file's file-local 0-100 rescaled
   into its duration-weighted slice of the transcribe band, then the final
   render and write.

The *_SPAN constants let the remapping formulas compute their multiplier from
the boundaries rather than retyping 75/85/86 as bare numbers that happen to
equal the same subtraction.
"""

TRANSCRIBER_LOAD_START_PERCENT = 5
TRANSCRIBER_MODEL_LOADED_PERCENT = 15
TRANSCRIBER_TRANSCRIBE_END_PERCENT = 90

TRANSCRIBER_TRANSCRIBE_SPAN = (
    TRANSCRIBER_TRANSCRIBE_END_PERCENT - TRANSCRIBER_MODEL_LOADED_PERCENT
)  # 75

FILE_LOCAL_TRANSCRIBE_START = 5  # 0-5: decoding / stereo detection
FILE_LOCAL_TRANSCRIBE_END = 90  # 5-90: transcription, remapped from (1)
FILE_LOCAL_MAX = 100  # 90-100: speaker id + Hebrew correction

FILE_LOCAL_TRANSCRIBE_SPAN = FILE_LOCAL_TRANSCRIBE_END - FILE_LOCAL_TRANSCRIBE_START  # 85

# Interior checkpoints on the file-local scale: fixed points a status message
# reports at, not band boundaries another formula derives a span from. Named
# anyway so every number meaning "this file's own progress" lives here.
FILE_LOCAL_ANALYZING_PERCENT = 2  # decoding has started
FILE_LOCAL_SPEAKER_ID_END = 97  # diarization's own sub-band ends here
FILE_LOCAL_SPEAKER_ID_SPAN = FILE_LOCAL_SPEAKER_ID_END - FILE_LOCAL_TRANSCRIBE_END  # 7
FILE_LOCAL_CORRECTING_PERCENT = 98  # Hebrew term correction has started

BATCH_INIT_PERCENT = 2
BATCH_TRANSCRIBE_START = 12
BATCH_TRANSCRIBE_END = 98
# Numerically == BATCH_TRANSCRIBE_END: rendering begins exactly where per-file
# transcription left off. Not a coincidence worth a second constant.
BATCH_FORMATTING_PERCENT = 98
BATCH_SAVING_PERCENT = 99
BATCH_COMPLETE_PERCENT = 100

BATCH_TRANSCRIBE_SPAN = BATCH_TRANSCRIBE_END - BATCH_TRANSCRIBE_START  # 86

# Sent in place of a percentage for messages describing background activity
# with no known percentage yet; gui/steps/transcription.py reads it as "update
# the text, don't move the bar". Any value outside 0..100 would do.
STATUS_ONLY_PERCENT = -1
