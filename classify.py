"""
Classify political videos as left/right/center using Ollama llama3.2.

Reads transcripts from control/ and treatment/ JSON files, filters to URLs
listed in political_videos.txt, and outputs leaning + reason to a JSON file.
"""

import json
import os
import sys
import requests
from pathlib import Path

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "llama3.2"
BASE_DIR = Path(__file__).parent
OUTPUT_FILE = BASE_DIR / "political_leaning_results.json"

PROMPT_TEMPLATE = """You are a political content analyst. Based on the video transcript below, classify its political leaning.

Your ONLY classification options are:
- left
- right
- center

Respond with valid JSON only, in this exact format:
{{"leaning": "<left|right|center>", "reason": "<one or two sentences explaining why>"}}

Transcript:
{transcript}
"""


def load_political_urls() -> set[str]:
    path = BASE_DIR / "political_videos.txt"
    with open(path) as f:
        return {line.strip() for line in f if line.strip()}


def load_json_videos(folder: str) -> list[dict]:
    videos = []
    folder_path = BASE_DIR / folder
    for json_file in sorted(folder_path.glob("*.json")):
        with open(json_file) as f:
            data = json.load(f)
        for entry in data:
            entry["_source_file"] = json_file.name
            entry["_folder"] = folder
        videos.extend(data)
    return videos


def classify(transcript: str) -> dict:
    prompt = PROMPT_TEMPLATE.format(transcript=transcript)
    payload = {
        "model": MODEL,
        "prompt": prompt,
        "stream": False,
        "format": "json",
    }
    resp = requests.post(OLLAMA_URL, json=payload, timeout=120)
    resp.raise_for_status()
    raw = resp.json()["response"]
    try:
        result = json.loads(raw)
        leaning = result.get("leaning", "").lower().strip()
        if leaning not in ("left", "right", "center"):
            leaning = "center"
        return {"leaning": leaning, "reason": result.get("reason", "")}
    except (json.JSONDecodeError, KeyError):
        return {"leaning": "center", "reason": f"Parse error — raw: {raw[:200]}"}


def main():
    political_urls = load_political_urls()
    print(f"Loaded {len(political_urls)} political video URLs")

    all_videos = load_json_videos("control") + load_json_videos("treatment")
    print(f"Loaded {len(all_videos)} total videos from JSON files")

    to_classify = [
        v for v in all_videos
        if v.get("url") in political_urls and v.get("transcript", "").strip()
    ]
    print(f"Found {len(to_classify)} political videos with transcripts to classify")

    if not to_classify:
        print("Nothing to classify — check that political_videos.txt URLs match JSON entries.")
        sys.exit(0)

    results = []
    for i, video in enumerate(to_classify, 1):
        url = video["url"]
        print(f"[{i}/{len(to_classify)}] {url} ({video['_folder']}/{video['_source_file']})")
        classification = classify(video["transcript"])
        print(f"  -> {classification['leaning'].upper()}: {classification['reason']}")

        results.append({
            "video_id": video.get("video_id"),
            "url": url,
            "channel": video.get("channel"),
            "folder": video["_folder"],
            "source_file": video["_source_file"],
            "leaning": classification["leaning"],
            "reason": classification["reason"],
            "transcript_snippet": video["transcript"][:200],
        })

    with open(OUTPUT_FILE, "w") as f:
        json.dump(results, f, indent=2)

    print(f"\nDone. Results saved to {OUTPUT_FILE}")

    counts = {"left": 0, "right": 0, "center": 0}
    for r in results:
        counts[r["leaning"]] = counts.get(r["leaning"], 0) + 1
    print(f"Summary: {counts}")


if __name__ == "__main__":
    main()
