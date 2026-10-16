"""Deletion of saved meetings, limited to one meeting folder at a time."""
import ctypes
from ctypes import wintypes
from pathlib import Path

from meeting_core import MEETINGS_DIR


def _recycle_folder(folder: Path):
    class FileOperation(ctypes.Structure):
        _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT),
                    ("pFrom", wintypes.LPCWSTR), ("pTo", wintypes.LPCWSTR),
                    ("fFlags", wintypes.WORD), ("fAnyOperationsAborted", wintypes.BOOL),
                    ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wintypes.LPCWSTR)]

    # Shell file operations require a fully qualified, double-null-terminated list.
    source = ctypes.create_unicode_buffer(str(folder) + "\0")
    operation = FileOperation()
    operation.wFunc = 3  # FO_DELETE
    operation.pFrom = ctypes.cast(source, wintypes.LPCWSTR)
    # Allow undo; confirm separately in the app; warn if Windows cannot recycle.
    operation.fFlags = 0x0040 | 0x0010 | 0x0004 | 0x0400 | 0x4000
    shell = ctypes.WinDLL("shell32", use_last_error=True)
    shell.SHFileOperationW.argtypes = [ctypes.POINTER(FileOperation)]
    shell.SHFileOperationW.restype = ctypes.c_int
    result = shell.SHFileOperationW(ctypes.byref(operation))
    if operation.fAnyOperationsAborted:
        raise OSError("Deletion was canceled. Refresh the meeting list to check its files.")
    if result:
        raise OSError(f"Windows could not move this meeting to the Recycle Bin (code {result}).")
    if folder.exists():
        raise OSError("The meeting folder is still present. Refresh the list and try again.")


def delete_saved_meeting(folder: Path, *, active_folder: Path | None = None, base: Path | None = None):
    root_path = base if base is not None else MEETINGS_DIR
    # Reject redirected storage locations before resolving the final deletion target.
    if root_path.is_symlink() or root_path.is_junction():
        raise ValueError("The meetings folder cannot be a linked directory for deletion.")
    root = root_path.resolve(strict=True)
    if folder.is_symlink() or folder.is_junction():
        raise ValueError("Linked meeting folders cannot be deleted from the app.")
    target = folder.resolve(strict=True)
    if target.parent != root or not target.is_dir():
        raise ValueError("Choose a meeting folder directly inside the saved meetings folder.")
    if active_folder is not None and target == active_folder.resolve():
        raise ValueError("Finish the active meeting before deleting it.")
    if not ((target / "meeting.json").is_file() or (target / "transcript.txt").is_file()):
        raise ValueError("This folder does not contain a saved meeting.")
    _recycle_folder(target)
