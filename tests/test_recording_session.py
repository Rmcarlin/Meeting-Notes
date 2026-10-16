import json
from pathlib import Path
import queue
import tempfile
import threading
import time
from types import SimpleNamespace as NS
import unittest

from audio_capture import AudioJob, Capture
from meeting_core import Meeting, Entry, subtitles
from recording_session import SessionRunner, segment_entry


class RecordingSessionTests(unittest.TestCase):
    def test_overlap_uses_word_times_to_keep_only_new_speech(self):
        segment = NS(words=[NS(start=.1, end=.4, word=" Old"),
                            NS(start=1.1, end=1.5, word=" new"),
                            NS(start=1.5, end=1.9, word=" words.")])
        entry = segment_entry(segment, AudioJob(Path("clip.wav"), 7, "Microphone", 1))
        self.assertEqual(entry.text, "new words.")
        self.assertAlmostEqual(entry.start, 8.1)
        self.assertAlmostEqual(entry.end, 8.9)
        segment.words = segment.words[:1]
        self.assertIsNone(segment_entry(segment, AudioJob(Path("clip.wav"), 7, "Microphone", 1)))

    def test_future_context_belongs_to_next_chunk(self):
        segment = NS(words=[NS(start=7.6, end=7.9, word=" Current"),
                            NS(start=8.2, end=8.6, word=" future.")])
        entry = segment_entry(segment, AudioJob(Path("clip.wav"), 0, "Microphone", 0, 8))
        self.assertEqual(entry.text, "Current")

    def test_stop_during_model_load_stops_capture_and_drains_saved_audio(self):
        started, loading, release, stopped = (threading.Event() for _ in range(4))
        stop = threading.Event()
        events = queue.Queue()

        class FakeCapture:
            def __init__(self, selections, folder, jobs, report, levels):
                self.jobs, self.folder = jobs, folder
                self.failed = threading.Event()
                self.formats, self.streams = [], []
            def start(self):
                self.started = time.monotonic()
                started.set()
            def stop(self):
                stopped.set()
                self.jobs.put(AudioJob(self.folder / "tail.wav", 0, "Microphone"))

        class Model:
            def transcribe(self, path, **kwargs):
                return iter([NS(start=0, end=2, text="We will send the agenda Friday.", words=None)]), NS(duration=2)

        def factory(*args, **kwargs):
            self.assertTrue(started.is_set(), "capture must start before model loading")
            loading.set()
            if not release.wait(5):
                raise RuntimeError("Test model was never released")
            return Model()

        with tempfile.TemporaryDirectory() as location:
            meeting = Meeting("Stop during load", Path(location))
            runner = SessionRunner(events, stop, {}, factory, FakeCapture)
            thread = threading.Thread(target=runner.run, args=(meeting, "base.en", [], None))
            thread.start()
            try:
                self.assertTrue(loading.wait(3))
                stop.set()
                self.assertTrue(stopped.wait(3), "capture must stop while model is still loading")
            finally:
                release.set()
                thread.join(5)
            self.assertFalse(thread.is_alive())
            self.assertEqual(len(meeting.entries), 1, "saved tail must be processed even after stop")
            metadata = json.loads((meeting.folder / "meeting.json").read_text())
            self.assertEqual(metadata["status"], "completed")
            self.assertIn("agenda Friday", (meeting.folder / "transcript.txt").read_text())
            self.assertTrue((meeting.folder / "transcript.srt").exists())

    def test_import_cancel_preserves_partial_results_and_original(self):
        stop = threading.Event()
        with tempfile.TemporaryDirectory() as location:
            original = Path(location) / "original.wav"
            original.write_bytes(b"original data")
            meeting = Meeting("Canceled import", Path(location) / "sessions")

            class Model:
                def transcribe(self, *args, **kwargs):
                    def segments():
                        yield NS(start=0, end=1, text="First sentence.", words=None)
                        stop.set()
                        yield NS(start=1, end=2, text="Should not be saved.", words=None)
                    return segments(), NS(duration=2)

            SessionRunner(queue.Queue(), stop, {"base.en": Model()}).run(meeting, "base.en", [], original)
            self.assertEqual([e.text for e in meeting.entries], ["First sentence."])
            self.assertEqual(original.read_bytes(), b"original data")
            metadata = json.loads((meeting.folder / "meeting.json").read_text())
            self.assertEqual(metadata["status"], "canceled")
            self.assertFalse(metadata["audio_retained"])

    def test_model_failure_preserves_capture_and_reports_review(self):
        with tempfile.TemporaryDirectory() as location:
            meeting = Meeting("Model failed", Path(location))

            class SampleCapture(Capture):
                def start(self):
                    self.started = time.monotonic()
                    buffer = queue.Queue()
                    buffer.put((b"\x01\x00" * 16000, self.started + 1))
                    buffer.put(None)
                    self._write(buffer, "Microphone", 16000, 1)

            def factory(*args, **kwargs):
                raise RuntimeError("No model available offline")

            SessionRunner(queue.Queue(), threading.Event(), {}, factory, SampleCapture).run(
                meeting, "base.en", [], None)
            metadata = json.loads((meeting.folder / "meeting.json").read_text())
            self.assertEqual(metadata["status"], "completed_with_errors")
            self.assertIn("offline", metadata["errors"][0])
            self.assertTrue(metadata["audio_retained"])
            self.assertGreater((meeting.folder / "audio/Microphone_full.wav").stat().st_size, 32000)

    def test_subtitles_preserve_milliseconds_and_time_order(self):
        result = subtitles([Entry(3.501, 4.7, "Microphone", "Later"),
                            Entry(.123, 2.04, "Meeting audio", "Earlier")])
        self.assertIn("1\n00:00:00,123 --> 00:00:02,040\nMeeting audio: Earlier", result)
        self.assertIn("2\n00:00:03,501 --> 00:00:04,700", result)
