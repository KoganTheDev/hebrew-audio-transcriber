"""
Tests for core/progress_scale.py.

The module holds no logic, so what is worth pinning is the relationships
between its three coordinate systems - the properties every remapping
formula in core/worker.py and core/transcriber.py silently assumes. A
constant edited in isolation that broke one of these would otherwise only
show up as a progress bar that jumps backwards during a real run.
"""

from speech_to_text.core import progress_scale as ps


def test_every_band_runs_forwards():
    assert ps.TRANSCRIBER_LOAD_START_PERCENT < ps.TRANSCRIBER_MODEL_LOADED_PERCENT
    assert ps.TRANSCRIBER_MODEL_LOADED_PERCENT < ps.TRANSCRIBER_TRANSCRIBE_END_PERCENT
    assert ps.FILE_LOCAL_TRANSCRIBE_START < ps.FILE_LOCAL_TRANSCRIBE_END
    assert ps.FILE_LOCAL_TRANSCRIBE_END < ps.FILE_LOCAL_MAX
    assert ps.BATCH_INIT_PERCENT < ps.BATCH_TRANSCRIBE_START
    assert ps.BATCH_TRANSCRIBE_START < ps.BATCH_TRANSCRIBE_END
    assert ps.BATCH_TRANSCRIBE_END <= ps.BATCH_SAVING_PERCENT
    assert ps.BATCH_SAVING_PERCENT < ps.BATCH_COMPLETE_PERCENT


def test_every_span_is_the_subtraction_of_its_own_boundaries():
    """
    The *_SPAN constants exist so the remapping formulas do not retype
    75/85/86 as bare numbers that happen to equal the same subtraction. If
    one drifted from its boundaries, every percentage derived from it would
    be quietly wrong rather than obviously broken.
    """
    assert ps.TRANSCRIBER_TRANSCRIBE_SPAN == (
        ps.TRANSCRIBER_TRANSCRIBE_END_PERCENT - ps.TRANSCRIBER_MODEL_LOADED_PERCENT
    )
    assert ps.FILE_LOCAL_TRANSCRIBE_SPAN == (
        ps.FILE_LOCAL_TRANSCRIBE_END - ps.FILE_LOCAL_TRANSCRIBE_START
    )
    assert ps.FILE_LOCAL_SPEAKER_ID_SPAN == (
        ps.FILE_LOCAL_SPEAKER_ID_END - ps.FILE_LOCAL_TRANSCRIBE_END
    )
    assert ps.BATCH_TRANSCRIBE_SPAN == (ps.BATCH_TRANSCRIBE_END - ps.BATCH_TRANSCRIBE_START)


def test_no_span_is_zero_so_no_remapping_can_divide_by_zero():
    assert ps.TRANSCRIBER_TRANSCRIBE_SPAN > 0
    assert ps.FILE_LOCAL_TRANSCRIBE_SPAN > 0
    assert ps.BATCH_TRANSCRIBE_SPAN > 0


def test_the_file_local_tail_leaves_room_for_speakers_and_correction():
    """
    Speaker identification and Hebrew correction report inside
    FILE_LOCAL_TRANSCRIBE_END..FILE_LOCAL_MAX, and both of their checkpoints
    have to fall in that window in that order or the bar moves backwards.
    """
    assert ps.FILE_LOCAL_TRANSCRIBE_END < ps.FILE_LOCAL_SPEAKER_ID_END
    assert ps.FILE_LOCAL_SPEAKER_ID_END < ps.FILE_LOCAL_CORRECTING_PERCENT
    assert ps.FILE_LOCAL_CORRECTING_PERCENT <= ps.FILE_LOCAL_MAX
    assert ps.FILE_LOCAL_ANALYZING_PERCENT < ps.FILE_LOCAL_TRANSCRIBE_START


def test_rendering_begins_exactly_where_per_file_transcription_ends():
    """Deliberate, not a coincidence - see the constant's own comment."""
    assert ps.BATCH_FORMATTING_PERCENT == ps.BATCH_TRANSCRIBE_END


def test_the_status_only_sentinel_can_never_collide_with_a_real_percentage():
    """
    gui/steps/transcription.py reads this as "update the text, leave the bar
    alone". Any value inside 0..100 would silently move the bar instead.
    """
    assert not 0 <= ps.STATUS_ONLY_PERCENT <= 100


def test_a_transcriber_percentage_remaps_into_the_file_local_band():
    """
    The formula in worker.py's _file_local_emitter, checked at both ends:
    the model-loaded point lands on the start of the file-local transcribe
    band, and transcription finishing lands on its end.
    """

    def remap(percent):
        return round(
            ps.FILE_LOCAL_TRANSCRIBE_START
            + (percent - ps.TRANSCRIBER_MODEL_LOADED_PERCENT)
            / ps.TRANSCRIBER_TRANSCRIBE_SPAN
            * ps.FILE_LOCAL_TRANSCRIBE_SPAN
        )

    assert remap(ps.TRANSCRIBER_MODEL_LOADED_PERCENT) == ps.FILE_LOCAL_TRANSCRIBE_START
    assert remap(ps.TRANSCRIBER_TRANSCRIBE_END_PERCENT) == ps.FILE_LOCAL_TRANSCRIBE_END
