"""
Tests for core/options.py.

TranscriptionOptions is a plain dataclass, so the things worth testing are
the two properties that are not obvious from the field list: that every
instance gets its own mutable containers rather than sharing one, and that
the whole object survives the pickle round trip it makes on its way into the
worker process.
"""

import pickle

from speech_to_text import config
from speech_to_text.core.options import TranscriptionOptions


def test_the_defaults_match_the_apps_configured_model_and_language():
    options = TranscriptionOptions()
    assert options.model_size == config.DEFAULT_MODEL
    assert options.language == config.LANGUAGE
    assert options.device == "cpu"


def test_two_instances_do_not_share_their_mutable_containers():
    """
    A bare `[]` or `{}` default would make every options object in the
    process alias the same list - one batch's durations would leak into the
    next run's progress arithmetic.
    """
    first = TranscriptionOptions()
    second = TranscriptionOptions()

    first.audio_durations.append(1.0)
    first.ui_strings["save"] = "Save"

    assert second.audio_durations == []
    assert second.ui_strings == {}


def test_total_duration_is_the_sum_of_every_files_duration():
    options = TranscriptionOptions(audio_durations=[10.0, 2.5, 0.5])
    assert options.total_duration == 13.0


def test_total_duration_of_an_unprobed_batch_is_zero_not_an_error():
    """
    The GUI always probes durations, but a direct caller need not. Worker's
    progress rescaling branches on total_duration > 0, so this has to be a
    number rather than a raise.
    """
    assert TranscriptionOptions().total_duration == 0


def test_the_whole_object_survives_the_trip_into_the_worker_process():
    """
    Instances cross a process boundary as a multiprocessing.Process argument,
    which pickles them. Anything unpicklable added here would only fail at
    run time, in the child, as an error nobody could trace back to options.
    """
    options = TranscriptionOptions(
        model_size="tiny",
        audio_durations=[3.0, 4.0],
        speaker_label="דובר {n}",
        failed_label="Transcription failed",
        ui_strings={"save": "Save"},
        num_speakers=3,
        terms_file="terms.txt",
    )

    # Round-tripping bytes this test just produced from an object it just
    # built - no untrusted input is involved, and pickle is exactly what
    # multiprocessing itself uses here, so a stand-in would not test it.
    restored = pickle.loads(pickle.dumps(options))

    assert restored == options
    assert restored.total_duration == 7.0


def test_num_speakers_defaults_to_a_count_rather_than_infer_it():
    """
    -1 means "infer the count", which is the weaker path: knowing the number
    exactly is the single biggest accuracy lever in diarization. The default
    is a real count for that reason.
    """
    assert TranscriptionOptions().num_speakers != -1
