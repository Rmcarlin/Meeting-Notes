"""Manual end-to-end check using a supplied recording; does not open a microphone."""
import sys
from faster_whisper import WhisperModel
from meeting_core import ROOT

if __name__ == "__main__":
    model = WhisperModel("tiny.en", device="cpu", compute_type="int8", download_root=str(ROOT / ".models"))
    segments, _ = model.transcribe(sys.argv[1], language="en", beam_size=1, vad_filter=True)
    text = " ".join(s.text.strip() for s in segments)
    print(text)
    if not all(word in text.lower() for word in ("meeting", "friday", "agenda")):
        raise SystemExit("Transcription did not contain the expected sample words.")
    print("PASS: local speech recognition on synthesized meeting audio")
