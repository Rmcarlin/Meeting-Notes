import json
from pathlib import Path
import queue
import tempfile
import threading
import time
import unittest
import wave

from audio_capture import Capture
from meeting_core import Entry, Meeting, draft_notes, saved_meetings


class MeetingTests(unittest.TestCase):
    def test_two_sources_are_saved_in_time_order_and_notes_keep_quotes(self):
        with tempfile.TemporaryDirectory() as folder:
            meeting = Meeting("Planning / meeting", Path(folder))
            meeting.add(Entry(9, 12, "Meeting audio", "We decided to move the launch."))
            meeting.add(Entry(2, 5, "Microphone", "I will send the agenda by Friday."))
            meeting.finish("completed")
            text = (meeting.folder / "transcript.txt").read_text(encoding="utf-8")
            self.assertLess(text.index("agenda"), text.index("launch"))
            notes = (meeting.folder / "notes.md").read_text(encoding="utf-8")
            self.assertIn("I will send the agenda by Friday.", notes)
            self.assertIn("We decided to move the launch.", notes)
            self.assertEqual(json.loads((meeting.folder / "meeting.json").read_text())["segments"], 2)
            journal = (meeting.folder / "transcript.jsonl").read_text().splitlines()
            self.assertEqual(len(journal), 2)

    def test_stop_preserves_partial_chunk_and_timestamps(self):
        with tempfile.TemporaryDirectory() as folder:
            jobs = queue.Queue()
            problems = []
            capture = Capture([], Path(folder), jobs, problems.append, chunk_seconds=8, overlap_seconds=1)
            capture.started = time.monotonic()
            buffer = queue.Queue()
            rate = 16000
            worker = threading.Thread(target=capture._write, args=(buffer, "Microphone", rate, 1))
            worker.start()
            # The one-second tail includes a second of context, but the master has no duplicates.
            buffer.put((b"\x01\x00" * rate * 9, capture.started + 9))
            buffer.put(None)
            worker.join(timeout=5)
            self.assertFalse(worker.is_alive())
            first, last = jobs.get_nowait(), jobs.get_nowait()
            with wave.open(str(first.path)) as audio:
                self.assertEqual(audio.getnframes(), rate * 9)
            self.assertEqual(first.duration, 8)
            with wave.open(str(last.path)) as audio:
                self.assertEqual(audio.getnframes(), rate * 2)
            self.assertEqual(last.offset, 7)
            self.assertEqual(last.trim_before, 1)
            self.assertEqual(last.duration, 1)
            with wave.open(str(Path(folder) / "Microphone_full.wav")) as audio:
                self.assertEqual(audio.getnframes(), rate * 9)
                self.assertEqual(audio.readframes(rate * 9), b"\x01\x00" * rate * 9)
            self.assertFalse(problems)

    def test_empty_meeting_does_not_invent_decisions(self):
        notes = draft_notes([], "Quiet meeting")
        self.assertIn("No speech transcribed yet.", notes)
        self.assertIn("No matching excerpts found.", notes)

    def test_library_keeps_transcripts_accessible_when_metadata_is_damaged(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            meeting = Meeting("Team planning", base)
            meeting.add(Entry(0, 2, "Microphone", "We will send an update."))
            meeting.finish("completed")
            damaged = base / "2020-01-01_older_session"
            damaged.mkdir()
            (damaged / "meeting.json").write_text("{broken", encoding="utf-8")
            (damaged / "transcript.txt").write_text("An older transcript.", encoding="utf-8")
            (base / "unrelated-folder").mkdir()
            library = saved_meetings(base)
            self.assertEqual(len(library), 2)
            self.assertEqual(library[0]["title"], "Team planning")
            self.assertEqual(library[1]["folder"], damaged)
            self.assertEqual(library[1]["status"], "unknown")


if __name__ == "__main__":
    unittest.main()
