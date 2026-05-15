"""One-off PDF size comparison between downloads and external references."""

from __future__ import annotations

import argparse
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SizeMismatch:
    """A same-name PDF whose byte size differs."""

    name: str
    download_path: Path
    reference_path: Path
    download_size: int
    reference_size: int

    @property
    def delta(self) -> int:
        """Return downloaded size minus reference size."""
        return self.download_size - self.reference_size


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Compare same-name PDF byte sizes between downloads subfolders "
            "and an external reference folder."
        )
    )
    parser.add_argument("--downloads", type=Path, default=Path("downloads"), help="Downloads root folder.")
    parser.add_argument("--reference", type=Path, default=Path("docs"), help="Reference PDF folder.")
    args = parser.parse_args()

    downloads = args.downloads.resolve()
    reference = args.reference.resolve()
    _require_dir(downloads, "--downloads")
    _require_dir(reference, "--reference")

    download_index, duplicate_downloads = _unique_index(downloads.glob("**/*.pdf"))
    reference_index, duplicate_references = _unique_index(reference.glob("*.pdf"))

    equal_count = 0
    mismatches: list[SizeMismatch] = []
    for name in sorted(download_index.keys() & reference_index.keys(), key=_sort_key):
        download_path = download_index[name]
        reference_path = reference_index[name]
        download_size = download_path.stat().st_size
        reference_size = reference_path.stat().st_size
        if download_size == reference_size:
            equal_count += 1
        else:
            mismatches.append(
                SizeMismatch(
                    name=download_path.name,
                    download_path=download_path,
                    reference_path=reference_path,
                    download_size=download_size,
                    reference_size=reference_size,
                )
            )

    missing_in_reference = sorted(download_index.keys() - reference_index.keys(), key=_sort_key)
    missing_in_downloads = sorted(reference_index.keys() - download_index.keys(), key=_sort_key)

    print(f"Compared same-name PDFs: {equal_count + len(mismatches)}")
    print(f"Same byte size: {equal_count}")
    print(f"Different byte size: {len(mismatches)}")
    print(f"Missing in reference: {len(missing_in_reference)}")
    print(f"Missing in downloads: {len(missing_in_downloads)}")

    if mismatches:
        print()
        print("Different byte size entries:")
        for item in mismatches:
            larger_source, larger_path, larger_size = _larger_file(item, downloads, reference)
            print(f"{item.name}: {larger_source}/{larger_path}={larger_size} bytes")

    _print_missing("Missing in reference", missing_in_reference, download_index, downloads)
    _print_missing("Missing in downloads", missing_in_downloads, reference_index, reference)

    _print_duplicates("Duplicate names in downloads", duplicate_downloads, downloads)
    _print_duplicates("Duplicate names in reference", duplicate_references, reference)

    return 0


def _require_dir(path: Path, option_name: str) -> None:
    if not path.is_dir():
        raise SystemExit(f"{option_name} is not a directory: {path}")


def _unique_index(paths: Iterable[Path]) -> tuple[dict[str, Path], dict[str, list[Path]]]:
    grouped: dict[str, list[Path]] = {}
    for raw_path in paths:
        path = Path(raw_path)
        if path.is_file():
            grouped.setdefault(path.name.lower(), []).append(path)

    unique: dict[str, Path] = {}
    duplicates: dict[str, list[Path]] = {}
    for name, matches in grouped.items():
        if len(matches) == 1:
            unique[name] = matches[0]
        else:
            duplicates[name] = sorted(matches, key=lambda path: str(path).lower())
    return unique, duplicates


def _sort_key(name: str) -> tuple[str, ...]:
    parts: list[str] = []
    current = ""
    is_digit = False
    for char in name:
        char_is_digit = char.isdigit()
        if current and char_is_digit != is_digit:
            parts.append(current.zfill(12) if is_digit else current)
            current = char
        else:
            current += char
        is_digit = char_is_digit
    if current:
        parts.append(current.zfill(12) if is_digit else current)
    return tuple(parts)


def _larger_file(item: SizeMismatch, downloads: Path, reference: Path) -> tuple[str, Path, int]:
    if item.download_size > item.reference_size:
        return "downloads", item.download_path.relative_to(downloads), item.download_size
    return "reference", item.reference_path.relative_to(reference), item.reference_size


def _print_missing(title: str, names: list[str], index: dict[str, Path], root: Path) -> None:
    if not names:
        return
    print()
    print(f"{title}:")
    for name in names:
        print(index[name].relative_to(root))


def _print_duplicates(title: str, duplicates: dict[str, list[Path]], root: Path) -> None:
    if not duplicates:
        return
    print()
    print(f"{title}:")
    for name in sorted(duplicates, key=_sort_key):
        joined = ", ".join(str(path.relative_to(root)) for path in duplicates[name])
        print(f"{name}: {joined}")


if __name__ == "__main__":
    raise SystemExit(main())
