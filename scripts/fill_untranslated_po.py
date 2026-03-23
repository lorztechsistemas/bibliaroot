#!/usr/bin/env python3
from __future__ import annotations

import ast
import sys
from pathlib import Path


def _parse_po_string(line: str) -> str:
    text = line.strip()
    if not text.startswith('"'):
        return ""
    return ast.literal_eval(text)


def _emit_msgstr_like_msgid(entry_lines: list[str]) -> list[str]:
    out: list[str] = []
    msgid_started = False
    msgstr_replaced = False
    msgid_chunks: list[str] = []
    i = 0
    while i < len(entry_lines):
        line = entry_lines[i]
        if line.startswith("msgid "):
            msgid_started = True
            msgid_chunks = [_parse_po_string(line[len("msgid "):])]
            out.append(line)
            i += 1
            while i < len(entry_lines) and entry_lines[i].lstrip().startswith('"'):
                msgid_chunks.append(_parse_po_string(entry_lines[i]))
                out.append(entry_lines[i])
                i += 1
            continue
        if line.startswith("msgstr ") and msgid_started and not msgstr_replaced:
            # Replace entire msgstr block with msgid content (skip only if header entry msgid is empty).
            if msgid_chunks == [""]:
                out.append(line)
                i += 1
                while i < len(entry_lines) and entry_lines[i].lstrip().startswith('"'):
                    out.append(entry_lines[i])
                    i += 1
                continue
            if len(msgid_chunks) <= 1:
                out.append(f'msgstr "{msgid_chunks[0]}"\n')
            else:
                out.append('msgstr ""\n')
                for chunk in msgid_chunks:
                    out.append(f'"{chunk}"\n')
            i += 1
            while i < len(entry_lines) and entry_lines[i].lstrip().startswith('"'):
                i += 1
            msgstr_replaced = True
            continue
        out.append(line)
        i += 1
    return out


def _msgstr_is_empty(entry_lines: list[str]) -> bool:
    if any(line.startswith("msgid_plural ") for line in entry_lines):
        return False
    for idx, line in enumerate(entry_lines):
        if line.startswith("msgid "):
            if line.strip() == 'msgid ""':
                return False  # header
        if line.startswith("msgstr "):
            parts = [_parse_po_string(line[len("msgstr "):])]
            j = idx + 1
            while j < len(entry_lines) and entry_lines[j].lstrip().startswith('"'):
                parts.append(_parse_po_string(entry_lines[j]))
                j += 1
            return "".join(parts) == ""
    return False


def fill_untranslated(path: Path) -> int:
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    entries: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        if line.strip() == "":
            if current:
                current.append(line)
                entries.append(current)
                current = []
            else:
                entries.append([line])
        else:
            current.append(line)
    if current:
        entries.append(current)

    changed = 0
    out: list[str] = []
    for entry in entries:
        if _msgstr_is_empty(entry):
            out.extend(_emit_msgstr_like_msgid(entry))
            changed += 1
        else:
            out.extend(entry)

    path.write_text("".join(out), encoding="utf-8")
    return changed


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: fill_untranslated_po.py FILE.po [FILE.po ...]")
        return 1
    total = 0
    for raw in argv[1:]:
        path = Path(raw)
        changed = fill_untranslated(path)
        total += changed
        print(f"{path}: {changed} preenchida(s)")
    print(f"Total: {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
