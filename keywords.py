import argparse
import json
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TREATMENT_DIR = os.path.join(SCRIPT_DIR, "treatment")
CONTROL_DIR = os.path.join(SCRIPT_DIR, "control")
KEYWORDS_FILE = os.path.join(SCRIPT_DIR, "keywords.txt")


def load_keywords():
    if not os.path.exists(KEYWORDS_FILE):
        return set()
    with open(KEYWORDS_FILE, "r") as f:
        keywords = set()
        for line in f:
            line = line.strip()
            if line and not line.startswith(" "):
                keywords.add(line.lower().split()[0])
        return keywords


def save_keyword(keyword, results):
    existing = load_keywords()
    with open(KEYWORDS_FILE, "a") as f:
        if keyword.lower() not in existing:
            f.write(keyword.lower() + "\n")
        else:
            f.write(f"{keyword.lower()} (re-run)\n")
        for folder_file, changed, total in results:
            if changed:
                f.write(f"  {folder_file}: {changed}/{total} entries updated\n")


def process_json(filepath, keyword):
    with open(filepath, "r") as f:
        data = json.load(f)

    changed = 0
    for entry in data:
        transcript = entry.get("transcript", "")
        if keyword.lower() in transcript.lower():
            if not entry.get("is_political"):
                entry["is_political"] = True
                changed += 1

    if changed:
        with open(filepath, "w") as f:
            json.dump(data, f, indent=2)

    return changed, len(data)


def main():
    parser = argparse.ArgumentParser(
        description="Mark transcript entries as political if they contain a keyword."
    )
    parser.add_argument("keyword", help="Keyword to search for in transcripts")
    args = parser.parse_args()

    keyword = args.keyword.strip()
    if not keyword:
        print("Error: keyword cannot be empty.")
        sys.exit(1)

    existing_keywords = load_keywords()
    if keyword.lower() in existing_keywords:
        print(f"Warning: '{keyword}' has already been run. Continuing anyway.")

    total_changed = 0
    total_entries = 0
    results = []

    for folder in [TREATMENT_DIR, CONTROL_DIR]:
        folder_name = os.path.basename(folder)
        json_files = [f for f in os.listdir(folder) if f.endswith(".json")]
        for filename in sorted(json_files):
            filepath = os.path.join(folder, filename)
            changed, count = process_json(filepath, keyword)
            total_changed += changed
            total_entries += count
            results.append((f"{folder_name}/{filename}", changed, count))
            print(f"{folder_name}/{filename}: {changed} entr{'y' if changed == 1 else 'ies'} updated out of {count}")

    save_keyword(keyword, results)
    print(f"\nDone. '{keyword}' marked {total_changed} entr{'y' if total_changed == 1 else 'ies'} as political across {total_entries} total.")
    print(f"Keyword logged to {KEYWORDS_FILE}")


if __name__ == "__main__":
    main()
