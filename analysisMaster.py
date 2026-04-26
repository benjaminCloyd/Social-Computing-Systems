"""
master.py — Download, transcribe, and classify YouTube Shorts in one pass.

The main thread downloads audio files sequentially. A background worker thread
immediately begins transcribing and classifying each file as it finishes
downloading, so processing overlaps with downloading.

Usage:
    python master.py [path/to/urls.txt]

If no .txt file is given, the first .txt found in the script directory is used.
Results are saved incrementally to political_analysis_master.json.

Requires:
    pip install yt-dlp faster-whisper ollama
    ollama serve   (running separately)
    ollama pull llama3.2
"""

import json
import queue
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

from faster_whisper import WhisperModel
import ollama

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

SCRIPT_DIR   = Path(__file__).parent
AUDIO_DIR    = SCRIPT_DIR / "audio"
OUTPUT_FILE  = SCRIPT_DIR / "political_analysis_master.json"
WHISPER_SIZE = "base"       # tiny | base | small | medium
OLLAMA_MODEL = "llama3.2"

PROMPT_TEMPLATE = """\
You are a content classifier. Decide whether the following transcript from a \
YouTube Short contains political content.

Political content includes: election/voting discussion, political parties or \
candidates, government policy, political ideology, social justice activism, \
protests, legislation, political news commentary, or calls to political action.

Respond with JSON only, no other text. Use this exact format:
{{"is_political": true/false, "confidence": "low"/"medium"/"high", "reason": "one sentence"}}

Transcript:
{transcript}"""

_DONE = object()  # sentinel that tells the worker thread to exit

# ---------------------------------------------------------------------------
# Parsing (same format as download_audio.py)
# ---------------------------------------------------------------------------

ENTRY_RE = re.compile(
    r'\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]\s+\[(\d+)/(\d+)\]\s+(.+?)\s+\|\s+(https://[^\s]+)\s+\(([0-9.]+)s[^)]*\)'
)


def parse_txt_file(filepath: Path) -> list[dict]:
    entries = []
    with open(filepath, "r", encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line:
                continue
            if "\t" in line:
                line = line.split("\t", 1)[1]
            m = ENTRY_RE.search(line)
            if not m:
                continue
            _, idx, _, channel, url, _ = m.groups()
            clean_url = url.rstrip("/")
            if clean_url == "https://www.youtube.com/shorts":
                continue
            video_id = clean_url.split("/shorts/")[-1].split("?")[0]
            if not video_id:
                continue
            entries.append({
                "index":    int(idx),
                "channel":  channel.lstrip("@"),
                "url":      url,
                "video_id": video_id,
            })
    return entries


# ---------------------------------------------------------------------------
# Download helpers
# ---------------------------------------------------------------------------

def _stem(entry: dict) -> str:
    channel = re.sub(r'[^\w\-]', '_', entry["channel"])
    return f"{entry['index']:04d}_{channel}_{entry['video_id']}"


def find_audio_file(entry: dict) -> Path | None:
    for f in AUDIO_DIR.glob(f"{_stem(entry)}.*"):
        return f
    return None


def download(entry: dict) -> Path | None:
    """Run yt-dlp for one entry. Returns the audio Path on success, None on failure."""
    out_template = str(AUDIO_DIR / f"{_stem(entry)}.%(ext)s")
    cmd = [
        "yt-dlp",
        "--format", "bestaudio/best",
        "--extract-audio",
        "--audio-format", "mp3",
        "--audio-quality", "0",
        "--no-playlist",
        "--quiet",
        "--progress",
        "--no-warnings",
        "-o", out_template,
        entry["url"],
    ]
    if subprocess.run(cmd).returncode == 0:
        return find_audio_file(entry)
    return None


# ---------------------------------------------------------------------------
# Transcription
# ---------------------------------------------------------------------------

def transcribe(model: WhisperModel, audio_file: Path) -> str | None:
    try:
        segments, _ = model.transcribe(
            str(audio_file),
            beam_size=5,
            language="en",
            vad_filter=True,
        )
        return " ".join(s.text.strip() for s in segments)
    except Exception as exc:
        print(f"  [transcribe] ✗ {exc}")
        return None


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

_JSON_RE = re.compile(r'\{.*?\}', re.DOTALL)


def classify(transcript: str) -> dict:
    prompt = PROMPT_TEMPLATE.format(transcript=transcript[:2000])
    try:
        response = ollama.chat(
            model=OLLAMA_MODEL,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0},
        )
        raw = response.message.content.strip()
        m = _JSON_RE.search(raw)
        if m:
            return json.loads(m.group())
    except json.JSONDecodeError:
        pass
    except Exception as exc:
        raise RuntimeError(f"Ollama error: {exc}") from exc
    return {"is_political": None, "confidence": "low", "reason": "parse error"}


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def load_results(path: Path) -> dict:
    if path.exists():
        with open(path, "r", encoding="utf-8") as fh:
            return {r["video_id"]: r for r in json.load(fh)}
    return {}


def save_results(path: Path, results: dict) -> None:
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(list(results.values()), fh, indent=2, ensure_ascii=False)
    tmp.replace(path)


# ---------------------------------------------------------------------------
# Worker thread: transcribe → classify → save (runs concurrently with downloads)
# ---------------------------------------------------------------------------

def worker(
    q: "queue.Queue[tuple | object]",
    results: dict,
    whisper_model: WhisperModel,
    output_file: Path,
) -> None:
    while True:
        item = q.get()
        if item is _DONE:
            q.task_done()
            break

        entry, audio_file = item
        vid   = entry["video_id"]
        label = f"{entry['channel']} | {vid}"

        print(f"  [worker] Transcribing {label} …", flush=True)
        t0 = time.time()
        transcript = transcribe(whisper_model, audio_file)
        elapsed = time.time() - t0

        if transcript is None:
            result = {
                "video_id": vid, "channel": entry["channel"],
                "url": entry["url"], "index": entry["index"],
                "filename": audio_file.name, "transcript": None,
                "is_political": None, "confidence": "low",
                "reason": "transcription failed",
            }
        else:
            print(f"  [worker] Classifying {label} … ({elapsed:.1f}s to transcribe)", flush=True)
            try:
                cls = classify(transcript)
            except RuntimeError as exc:
                print(f"  [worker] ✗ {exc}")
                cls = {"is_political": None, "confidence": "low", "reason": "ollama error"}

            is_pol = cls.get("is_political")
            flag   = "POLITICAL" if is_pol else ("not political" if is_pol is False else "unclear")
            print(f"  [worker] {label}  →  {flag} [{cls.get('confidence', '')}]  {cls.get('reason', '')}")

            result = {
                "video_id": vid, "channel": entry["channel"],
                "url": entry["url"], "index": entry["index"],
                "filename": audio_file.name, "transcript": transcript,
                "is_political": is_pol,
                "confidence":   cls.get("confidence", ""),
                "reason":       cls.get("reason", ""),
            }

        results[vid] = result
        save_results(output_file, results)
        q.task_done()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    if len(sys.argv) > 1:
        txt_file = Path(sys.argv[1])
        if not txt_file.is_absolute():
            txt_file = SCRIPT_DIR / txt_file
    else:
        txt_files = sorted(SCRIPT_DIR.glob("*.txt"))
        if not txt_files:
            print("No .txt file found in", SCRIPT_DIR)
            sys.exit(1)
        txt_file = txt_files[0]

    if not txt_file.exists():
        print(f"File not found: {txt_file}")
        sys.exit(1)

    print(f"Reading: {txt_file.name}")
    entries = parse_txt_file(txt_file)
    print(f"Parsed {len(entries)} valid Shorts entries")

    AUDIO_DIR.mkdir(exist_ok=True)

    results = load_results(OUTPUT_FILE)
    if results:
        print(f"Resuming — {len(results)} already processed")

    # Classify entries: fully done / need process only / need download+process
    to_download    = []
    process_only   = []
    for entry in entries:
        vid = entry["video_id"]
        if vid in results:
            continue
        audio_file = find_audio_file(entry)
        if audio_file:
            process_only.append((entry, audio_file))
        else:
            to_download.append(entry)

    print(f"  {len(to_download)} need download + process")
    print(f"  {len(process_only)} need process only (audio already exists)\n")

    if not to_download and not process_only:
        print("Nothing left to do.")
        return

    # Verify Ollama is reachable before we start
    try:
        ollama.list()
    except Exception:
        print("Error: Cannot connect to Ollama. Make sure it's running:\n  ollama serve")
        sys.exit(1)

    print(f"Loading Whisper model '{WHISPER_SIZE}' on CPU …")
    whisper_model = WhisperModel(WHISPER_SIZE, device="cpu", compute_type="int8")
    print("Model ready.\n")

    work_queue: queue.Queue = queue.Queue()

    worker_thread = threading.Thread(
        target=worker,
        args=(work_queue, results, whisper_model, OUTPUT_FILE),
        daemon=True,
    )
    worker_thread.start()

    # Queue files that already have audio so the worker can start right away
    for item in process_only:
        work_queue.put(item)

    # Download loop — each completed download is immediately queued for the worker
    dl_ok = dl_failed = 0
    try:
        for i, entry in enumerate(to_download, 1):
            print(f"[{i}/{len(to_download)}] Downloading {entry['channel']} | {entry['video_id']}")
            audio_file = download(entry)
            if audio_file:
                dl_ok += 1
                work_queue.put((entry, audio_file))
            else:
                print(f"  ✗ download failed: {entry['video_id']}")
                dl_failed += 1
    except KeyboardInterrupt:
        print("\nDownload interrupted — waiting for worker to finish queued items …")

    work_queue.put(_DONE)
    worker_thread.join()

    political = sum(1 for r in results.values() if r.get("is_political"))
    print(f"\nDone.")
    if to_download:
        print(f"  Downloads:  {dl_ok} ok, {dl_failed} failed")
    print(f"  Processed:  {len(results)} total, {political} political")
    print(f"  Results:    {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
