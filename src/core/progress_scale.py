"""How far along a run is, in the two units the UI needs: percentages for
the progress bar, and the work stream (audio-seconds, measured seconds) for
the time estimate - a bar position is the wrong thing to project time from.

A percentage crosses three scales, and every boundary lives here once:

1. Transcriber scale (core/transcriber.py): model loading and transcription,
   passed to the GUI verbatim while the model loads.
2. File-local scale (worker._transcribe_one): one file's own 0-100.
3. Batch scale (worker.run_transcription_process): each file's 0-100 rescaled
   into its duration-weighted slice of the transcribe band.
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

# Fixed checkpoints on the file-local scale.
FILE_LOCAL_ANALYZING_PERCENT = 2  # decoding has started
FILE_LOCAL_SPEAKER_ID_END = 97  # diarization's own sub-band ends here
FILE_LOCAL_CORRECTING_PERCENT = 98  # Hebrew term correction has started

BATCH_INIT_PERCENT = 2
# Exactly where model loading ends: any lower and the bar steps backwards when
# the first file starts.
BATCH_TRANSCRIBE_START = TRANSCRIBER_MODEL_LOADED_PERCENT
BATCH_TRANSCRIBE_END = 98
# Rendering starts where per-file transcription ends.
BATCH_FORMATTING_PERCENT = 98
BATCH_SAVING_PERCENT = 99
BATCH_COMPLETE_PERCENT = 100

BATCH_TRANSCRIBE_SPAN = BATCH_TRANSCRIBE_END - BATCH_TRANSCRIBE_START  # 86

# "Update the text, don't move the bar" - for activity with no percentage.
STATUS_ONLY_PERCENT = -1


# --- the work stream ---------------------------------------------------
#
# Measurements, not a bar position: every percent does not cost the same time
# (the VAD pass sits at a fixed 5% for over a minute on a long file), so the
# GUI divides measured wall clock by real work. Sent beside the progress tuples
# (core/worker.py):
#
#   ("work", audio_done, audio_total, monotonic) - audio-seconds decoded so
#       far, batch-wide, and the batch total.
#   ("phase", name, seconds, monotonic) - one pipeline phase and the wall clock
#       it took; seconds is None when it has only just started, so the GUI can
#       count up through phases with no progress of their own (diarization).

WORK_PHASE_DECODE = "decode"  # PyAV decode + the true-stereo check
WORK_PHASE_PREPARE = "prepare"  # faster-whisper's VAD pass, before segment 1
WORK_PHASE_TRANSCRIBE = "transcribe"  # one file's ASR, start to last segment
WORK_PHASE_DIARIZE = "diarize"  # the speaker pass, overlapped with the above
# The part of diarization left once transcription ends - the only part anyone
# waits for, since the rest runs underneath transcription.
WORK_PHASE_DIARIZE_WAIT = "diarize_wait"
WORK_PHASE_ASSIGN = "assign_speakers"
WORK_PHASE_CORRECT = "hebrew_correction"
WORK_PHASE_RENDER = "render"  # HTML render + atomic write

# "This phase has begun." None, since any number could be a real duration.
WORK_PHASE_STARTED = None
