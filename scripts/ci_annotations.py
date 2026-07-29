from __future__ import annotations

import argparse
import xml.etree.ElementTree as ET
from collections.abc import Iterable, Sequence
from pathlib import Path

MAX_MESSAGE_CHARS = 8_000


def _escape_data(value: str) -> str:
    return value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _escape_property(value: str) -> str:
    return _escape_data(value).replace(":", "%3A").replace(",", "%2C")


def emit_error(
    *, title: str, message: str, file: str | None = None, line: str | None = None
) -> None:
    properties = [f"title={_escape_property(title)}"]
    if file:
        properties.append(f"file={_escape_property(file)}")
    if line and line.isdigit():
        properties.append(f"line={line}")
    bounded_message = message[-MAX_MESSAGE_CHARS:]
    print(f"::error {','.join(properties)}::{_escape_data(bounded_message)}")


def report_junit(paths: Iterable[Path]) -> int:
    reported = 0
    for path in paths:
        if not path.is_file():
            continue
        root = ET.parse(path).getroot()
        for testcase in root.iter("testcase"):
            failure = testcase.find("failure")
            if failure is None:
                failure = testcase.find("error")
            if failure is None:
                continue
            test_name = testcase.attrib.get("name", "pytest failure")
            class_name = testcase.attrib.get("classname")
            title = f"{class_name}.{test_name}" if class_name else test_name
            message = "\n".join(
                part for part in (failure.attrib.get("message"), failure.text) if part
            )
            emit_error(
                title=title,
                message=message or "pytest reported a failure without details",
                file=testcase.attrib.get("file"),
                line=testcase.attrib.get("line"),
            )
            reported += 1
    return reported


def report_text(path: Path, *, title: str) -> int:
    if not path.is_file():
        return 0
    message = path.read_text(encoding="utf-8", errors="replace")
    if not message.strip():
        return 0
    if len(message) > MAX_MESSAGE_CHARS:
        marker = "\n... bounded diagnostic omitted middle content ...\n"
        head_chars = (MAX_MESSAGE_CHARS - len(marker)) // 2
        tail_chars = MAX_MESSAGE_CHARS - len(marker) - head_chars
        message = f"{message[:head_chars]}{marker}{message[-tail_chars:]}"
    emit_error(title=title, message=message)
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Turn bounded CI diagnostics into GitHub error annotations."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    junit_parser = subparsers.add_parser("junit")
    junit_parser.add_argument("paths", nargs="+", type=Path)

    text_parser = subparsers.add_parser("text")
    text_parser.add_argument("path", type=Path)
    text_parser.add_argument("--title", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "junit":
        report_junit(args.paths)
    else:
        report_text(args.path, title=args.title)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
