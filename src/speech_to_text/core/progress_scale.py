"""Named boundaries for the transcription progress bar, and the work stream
the time estimate is computed from.

Two different things live here because they answer the same question - "how
far along is this run?" - in the two different units the UI needs. The
percentage is for the BAR. The work stream, at the bottom of this file, is
for the CLOCK: it carries audio-seconds and measured wall-clock seconds
rather than a position on a 0-100 scale, because a percentage is the wrong
thing to project time from (see WORK_ constants below).

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


# --- the work stream -------------------------------------------------------
#
# Everything above is a POSITION ON A BAR. None of it is a quantity of work,
# and the difference is what made "Est. remaining" wrong: the old estimate
# was elapsed * (100 - percent) / percent, which assumes every percent costs
# the same wall clock. Measured on this machine, it does not come close -
# the model-load band can be twenty minutes on a first run or two seconds on
# a warm one, and a file's diarization tail (see FILE_LOCAL_SPEAKER_ID_END)
# ran 280s on one 15-minute recording while the bar did not move at all.
#
# So the worker reports work in units that mean something on their own, and
# the GUI divides measured wall clock by them. Two message kinds, both plain
# numbers, both crossing the process boundary alongside the existing
# ("progress", ...) and ("status", ...) tuples (see core/worker.py):
#
#   ("work", audio_done, audio_total, monotonic)
#       Audio-seconds decoded so far, BATCH-WIDE, and the batch total. This
#       is the honest denominator: it is what faster-whisper actually
#       charges for, it is already known exactly (segment.end against a
#       PyAV container probe - see gui/audio_utils.py), and unlike a
#       percentage it does not need a scale to be interpreted.
#
#   ("phase", name, seconds, monotonic)
#       One named phase of the pipeline, with the wall clock it really took.
#       seconds is None when the phase has only just STARTED - which is what
#       lets the GUI count up through a phase that reports no progress of
#       its own (diarization, which deliberately has no percentage callback)
#       instead of showing a frozen bar.
#
# Both are measurements, not estimates. Nothing here predicts anything; the
# prediction is one division, and it happens in the GUI where the clock is.

WORK_PHASE_DECODE = "decode"  # PyAV decode + the true-stereo check
WORK_PHASE_PREPARE = "prepare"  # faster-whisper's VAD pass, before segment 1
WORK_PHASE_TRANSCRIBE = "transcribe"  # one file's ASR, start to last segment
WORK_PHASE_DIARIZE = "diarize"  # the speaker pass, overlapped with the above
# What is left of diarization once transcription has finished, i.e. the part
# the user actually waits through. Distinct from WORK_PHASE_DIARIZE, which is
# diarization's own total cost: most of that is hidden underneath
# transcription and costs nobody anything. Only the overhang belongs in a
# time estimate, and only the overhang is a phase with a visible start.
WORK_PHASE_DIARIZE_WAIT = "diarize_wait"
WORK_PHASE_ASSIGN = "assign_speakers"
WORK_PHASE_CORRECT = "hebrew_correction"
WORK_PHASE_RENDER = "render"  # HTML render + atomic write

# Sent in place of a duration to mean "this phase has begun, and how long it
# will take is not known yet". None rather than a numeric sentinel: every
# other value on this channel is a real measured duration, and there is no
# number that could not also be one.
WORK_PHASE_STARTED = None
