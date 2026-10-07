#!/usr/bin/env python3
"""fecr-icerik deposunun kökündeki liste.json dizinini üretir.

Uygulama klasör listesini GitHub içerik API'sinden alır (anahtarsız, IP başına saatte 60 istek).
Sınır dolarsa `RemoteContent.fetchIndex` bu dosyayı raw.githubusercontent.com'dan okur. Biçim API ile
aynıdır: klasör adı → [{type, name, sha (git blob), size, download_url}]. Yalnızca kök klasörlerin
doğrudan içindeki dosyalar yazılır; API de alt klasörleri dosya olarak listelemez.

Her içerik değişikliğinde, commit'ten sonra çalıştırın ve liste.json'u ayrı commit'le gönderin:
    python3 Tools/build_content_index.py <fecr-icerik klonu> [--check]
--check: dosya güncel değilse yazmadan 1 ile çıkar.
"""
import json
import subprocess
import sys
from pathlib import Path

REPOSITORY = "gturkmenlabs/fecr-icerik"
BRANCH = "main"
INDEX = "liste.json"


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout


def build(repo: Path) -> dict:
    index = {}
    for line in git(repo, "ls-tree", "HEAD").splitlines():
        meta, folder = line.split("\t", 1)
        if meta.split()[1] != "tree":
            continue
        entries = []
        for child in git(repo, "ls-tree", "-l", "HEAD", f"{folder}/").splitlines():
            meta, path = child.split("\t", 1)
            _, kind, sha, size = meta.split()
            if kind != "blob":
                continue
            entries.append({
                "type": "file",
                "name": path.rsplit("/", 1)[-1],
                "sha": sha,
                "size": int(size),
                "download_url": f"https://raw.githubusercontent.com/{REPOSITORY}/{BRANCH}/{path}",
            })
        index[folder] = sorted(entries, key=lambda e: e["name"])
    return index


def main() -> int:
    args = [a for a in sys.argv[1:] if a != "--check"]
    if len(args) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    repo = Path(args[0])
    text = json.dumps(build(repo), ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    target = repo / INDEX
    if "--check" in sys.argv:
        current = target.read_text(encoding="utf-8") if target.exists() else ""
        if current != text:
            print(f"{INDEX} güncel değil", file=sys.stderr)
            return 1
        return 0
    target.write_text(text, encoding="utf-8")
    print(f"{target}: {sum(len(v) for v in json.loads(text).values())} dosya, {len(json.loads(text))} klasör")
    return 0


if __name__ == "__main__":
    sys.exit(main())
