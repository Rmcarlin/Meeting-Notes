from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from meeting_core import Meeting
from meeting_storage import delete_saved_meeting


class DeleteMeetingTests(unittest.TestCase):
    def test_recycles_only_the_selected_meeting(self):
        with tempfile.TemporaryDirectory() as location:
            base = Path(location) / "meetings"
            first = Meeting("First meeting", base)
            other = Meeting("Keep this meeting", base)
            with patch("meeting_storage._recycle_folder") as recycle:
                delete_saved_meeting(first.folder, base=base)
            recycle.assert_called_once_with(first.folder.resolve())
            self.assertTrue((other.folder / "transcript.txt").exists())

    def test_rejects_active_meeting_root_nested_folder_and_outside_folder(self):
        with tempfile.TemporaryDirectory() as location:
            base = Path(location) / "meetings"
            meeting = Meeting("Active meeting", base)
            outside = Meeting("Outside storage", Path(location) / "elsewhere")
            with patch("meeting_storage._recycle_folder") as recycle:
                with self.assertRaises(ValueError):
                    delete_saved_meeting(meeting.folder, base=base, active_folder=meeting.folder)
                for target in (base, meeting.folder / "audio", outside.folder):
                    with self.subTest(target=target):
                        with self.assertRaises(ValueError):
                            delete_saved_meeting(target, base=base)
                recycle.assert_not_called()

    def test_rejects_unrelated_folder_and_reports_recycle_failure(self):
        with tempfile.TemporaryDirectory() as location:
            base = Path(location)
            unrelated = base / "unrelated"
            unrelated.mkdir()
            with patch("meeting_storage._recycle_folder") as recycle:
                with self.assertRaises(ValueError):
                    delete_saved_meeting(unrelated, base=base)
                recycle.assert_not_called()
            meeting = Meeting("Saved meeting", base)
            with patch("meeting_storage._recycle_folder", side_effect=OSError("File is in use")):
                with self.assertRaises(OSError):
                    delete_saved_meeting(meeting.folder, base=base)
            self.assertTrue(meeting.folder.exists())
