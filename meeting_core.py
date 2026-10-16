"""Local meeting storage and conservative, extractive draft notes."""
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
import json
import re
import uuid

ROOT = Path(__file__).resolve().parent
MEETINGS_DIR = ROOT / "meetings"


def atomic_text(path: Path, content: str):
    """Replace complete documents without exposing partially written contents."""
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def subtitles(entries: list["Entry"]) -> str:
    def clock(seconds):
        millis = max(0, round(seconds * 1000))
        return f"{timestamp(millis // 1000)},{millis % 1000:03}"
    return "".join(f"{i}\n{clock(e.start)} --> {clock(max(e.end, e.start + .01))}\n"
                   f"{e.source}: {e.text}\n\n"
                   for i, e in enumerate(sorted(entries, key=lambda e: e.start), 1))


def saved_meetings(base: Path | None = None) -> list[dict]:
    """List sessions without requiring every metadata file to be readable."""
    folder = base if base is not None else MEETINGS_DIR
    if not folder.exists():
        return []
    result = []
    for path in folder.iterdir():
        if not path.is_dir():
            continue
        try:
            metadata = json.loads((path / "meeting.json").read_text(encoding="utf-8"))
            if not isinstance(metadata, dict):
                metadata = {}
        except (OSError, ValueError):
            metadata = {}
        if not metadata and not (path / "transcript.txt").exists():
            continue
        result.append({"folder": path, "title": str(metadata.get("title") or path.name),
                       "created": str(metadata.get("created") or ""),
                       "status": str(metadata.get("status") or "unknown")})
    return sorted(result, key=lambda item: item["folder"].name, reverse=True)


def timestamp(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 3600:02}:{seconds // 60 % 60:02}:{seconds % 60:02}"


@dataclass
class Entry:
    start: float
    end: float
    source: str
    text: str


def draft_notes(entries: list[Entry], title: str) -> str:
    ordered = sorted(entries, key=lambda e: e.start)
    groups = {
        "Possible action items": r"\b(will|i'll|we'll|need to|needs to|follow up|action item|assigned|send|prepare|schedule)\b",
        "Possible decisions": r"\b(agreed|decided|decision|approved|go ahead|settled on)\b",
        "Dates and deadlines mentioned": r"\b(deadline|due|tomorrow|next week|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
    }
    lines = [f"# {title}", "", "Draft notes — review against the transcript.",
             "These are matching transcript excerpts, not an AI summary. Speakers, owners, and commitments are not verified.", ""]
    for heading, pattern in groups.items():
        lines += [f"## {heading}", ""]
        matches = [e for e in ordered if re.search(pattern, e.text, re.I)]
        lines += [f"- [{timestamp(e.start)} · {e.source}] {e.text}" for e in matches]
        if not matches:
            lines.append("No matching excerpts found.")
        lines.append("")
    lines += ["## Discussion excerpts", ""]
    lines += [f"- [{timestamp(e.start)} · {e.source}] {e.text}" for e in ordered[:12]]
    if not ordered:
        lines.append("No speech transcribed yet.")
    return "\n".join(lines) + "\n"


class Meeting:
    def __init__(self, title: str, base: Path | None = None):
        self.title = title.strip() or "Untitled meeting"
        safe = re.sub(r"[^\w -]", "", self.title)[:50].strip() or "meeting"
        name = f"{datetime.now():%Y-%m-%d_%H-%M-%S}_{safe}_{uuid.uuid4().hex[:6]}"
        self.folder = (base if base is not None else MEETINGS_DIR) / name
        (self.folder / "audio").mkdir(parents=True)
        self.entries: list[Entry] = []
        self.errors: list[str] = []
        self.created = datetime.now().astimezone().isoformat()
        self.details = {}
        self.finish("preparing")

    def add(self, entry: Entry):
        with (self.folder / "transcript.jsonl").open("a", encoding="utf-8") as out:
            out.write(json.dumps(asdict(entry), ensure_ascii=False) + "\n")
        self.entries.append(entry)
        with (self.folder / "transcript.txt").open("a", encoding="utf-8") as out:
            out.write(f"[{timestamp(entry.start)}] {entry.source}: {entry.text}\n")

    def finish(self, status: str):
        # Re-sort the final transcript because two audio sources can finish out of order.
        ordered = sorted(self.entries, key=lambda e: e.start)
        content = "".join(f"[{timestamp(e.start)}] {e.source}: {e.text}\n" for e in ordered)
        atomic_text(self.folder / "transcript.txt", content)
        atomic_text(self.folder / "transcript.srt", subtitles(ordered))
        atomic_text(self.folder / "notes.md", draft_notes(ordered, self.title))
        metadata = {"title": self.title, "created": self.created, "status": status,
                    "segments": len(ordered), "errors": self.errors,
                    "audio_retained": any((self.folder / "audio").glob("*.wav")),
                    "speaker_identification": False, **self.details}
        atomic_text(self.folder / "meeting.json", json.dumps(metadata, indent=2, ensure_ascii=False))
