"""Best-effort, closed-field Windows Application Error evidence; never a gate."""

from __future__ import annotations

import argparse
import ast
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import xml.etree.ElementTree as ET  # nosec B405: bounded input, DTD/entities rejected below


NS = "{http://schemas.microsoft.com/win/2004/08/events/event}"
MAX_EVENTS = 8
QUERY_LIMIT = 64
MAX_XML_BYTES = 2 * 1024 * 1024
QUERY_TIMEOUT = 10
MODULE = re.compile(r"[A-Za-z0-9_.+-]{1,64}\.(dll|exe|pyd)", re.IGNORECASE | re.ASCII)
VERSION = re.compile(r"[0-9]{1,5}(\.[0-9]{1,5}){0,3}")
HEX_INPUT = re.compile(r"(?:0[xX])?([0-9a-fA-F]{1,16})")
HEX_OUTPUT = re.compile(r"0x[0-9a-f]{1,16}")
REASONS = frozenset({
    "invalid_since", "query_failed", "query_timeout", "invalid_xml",
    "query_too_large", "collector_error",
})


def allowed_apps() -> frozenset[str]:
    """Exact spec basenames, including the two versioned outer executables.

    Source: packaging/metroliza_{onedir,onefile,portable_onefile}.spec.
    Read only literal release metadata, without importing/executing product code.
    """
    path = Path(__file__).resolve().parents[1] / "src/metroliza/app/version.py"
    values = {}
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    values[target.id] = node.value.value
    release, build = values.get("RELEASE_VERSION"), values.get("VERSION_DATE")
    if (not isinstance(release, str) or not re.fullmatch(r"[0-9]{4}\.[0-9]{2}[a-z0-9]+", release)
            or not isinstance(build, str) or not re.fullmatch(r"[0-9]{6}", build)):
        raise ValueError("invalid_release_metadata")
    return frozenset({
        "metroliza_application.exe", "metroliza.exe",
        "metroliza_ocr_worker.exe", "metroliza_compute_worker.exe",
        f"metroliza_p_{release}({build}).exe", f"metroliza_{release}_{build}.exe",
    })


def _utc(value: str) -> datetime:
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,7})?(?:Z|\+00:00)", value):
        raise ValueError("invalid_timestamp")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _hex(value: str) -> str:
    match = HEX_INPUT.fullmatch(value)
    return "0x" + match[1].lower() if match else "unavailable"


def _unavailable(reason: str) -> dict:
    return {"schema_version": 1, "status": "unavailable", "reason": reason}


def _event_fields(event: ET.Element, since: datetime, apps: frozenset[str]):
    system = event.find(f"{NS}System")
    if system is None or system.findtext(f"{NS}EventID") != "1000":
        return None
    provider = system.find(f"{NS}Provider")
    created = system.find(f"{NS}TimeCreated")
    if provider is None or provider.get("Name") != "Application Error" or created is None:
        return None
    try:
        timestamp = _utc(created.get("SystemTime", ""))
    except ValueError:
        return None
    if timestamp < since:
        return None
    # Named fields avoid dependence on insertion-string order across Windows builds.
    data = {}
    for item in event.findall(f"{NS}EventData/{NS}Data"):
        name = item.get("Name")
        if name in data:
            return None  # ambiguous duplicate fields cannot identify the fault
        data[name] = item.text or ""
    raw_app = data.get("AppName", "")
    app = raw_app.lower() if raw_app.isascii() else ""
    if app not in apps:
        return None
    module, version = data.get("ModuleName", ""), data.get("ModuleVersion", "")
    return timestamp, {
        "app": app,
        "module": module if MODULE.fullmatch(module) else "other",
        "module_version": version if VERSION.fullmatch(version) else "unavailable",
        "exception_code": _hex(data.get("ExceptionCode", "")),
        "fault_offset": _hex(data.get("FaultingOffset", "")),
        "seconds_after_since": min(int((timestamp - since).total_seconds()), 2147483647),
    }


def reduce_events(raw: bytes, since: datetime) -> dict:
    """Parse wevtutil XML fragments or an Events document; retain no raw text."""
    if len(raw) > MAX_XML_BYTES:
        return _unavailable("query_too_large")
    try:
        encoding = "utf-16" if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"
        if not raw.startswith((b"\xff\xfe", b"\xfe\xff")) and b"\x00" in raw:
            encoding = "utf-16-le"
        # A foreign event in the console code page must not discard the whole
        # receipt; only allowlisted, regex-checked fields survive anyway.
        xml = raw.decode(encoding, errors="replace").strip()
        if "<!DOCTYPE" in xml.upper() or "<!ENTITY" in xml.upper():
            return _unavailable("invalid_xml")
        xml = re.sub(r"^<\?xml[^?]*\?>", "", xml)
        root = ET.fromstring("<Events>" + xml + "</Events>")  # nosec B314: DTD/entities rejected
        candidates = list(root.iter(f"{NS}Event"))
        apps = allowed_apps()
        events = [_event_fields(event, since, apps) for event in candidates]
        kept = sorted((item for item in events if item is not None), key=lambda item: item[0], reverse=True)
        return {
            "schema_version": 1, "status": "available",
            "events": [item[1] for item in kept[:MAX_EVENTS]],
            # Hitting the query cap can hide older eligible events, even if none matched.
            "truncated": len(kept) > MAX_EVENTS or len(candidates) >= QUERY_LIMIT,
        }
    except (UnicodeError, ET.ParseError):
        return _unavailable("invalid_xml")


def collect(since: str) -> dict:
    """All failures become closed unavailable receipts, without exception text."""
    try:
        try:
            start = _utc(since)
        except (ValueError, TypeError):
            return _unavailable("invalid_since")
        stamp = start.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        query = f"*[System[(EventID=1000) and TimeCreated[@SystemTime>='{stamp}']]]"
        result = subprocess.run(
            ["wevtutil", "qe", "Application", f"/q:{query}", "/f:xml", "/rd:true", "/c:64"],
            capture_output=True, timeout=QUERY_TIMEOUT, check=False,
        )
        if result.returncode != 0:
            return _unavailable("query_failed")
        return reduce_events(result.stdout, start)
    except subprocess.TimeoutExpired:
        return _unavailable("query_timeout")
    except OSError:
        return _unavailable("query_failed")
    except Exception:
        return _unavailable("collector_error")


def _valid_event(event: object, apps: frozenset[str]) -> bool:
    if not isinstance(event, dict) or set(event) != {
        "app", "module", "module_version", "exception_code", "fault_offset", "seconds_after_since",
    }:
        return False
    if not all(isinstance(event[key], str) for key in event if key != "seconds_after_since"):
        return False
    return (
        event["app"] in apps
        and (event["module"] == "other" or MODULE.fullmatch(event["module"]) is not None)
        and (event["module_version"] == "unavailable" or VERSION.fullmatch(event["module_version"]) is not None)
        and all(event[key] == "unavailable" or HEX_OUTPUT.fullmatch(event[key]) is not None
                for key in ("exception_code", "fault_offset"))
        and type(event["seconds_after_since"]) is int
        and 0 <= event["seconds_after_since"] <= 2147483647
    )


def validate_receipt(receipt: object) -> bool:
    try:
        if not isinstance(receipt, dict) or type(receipt.get("schema_version")) is not int or receipt["schema_version"] != 1:
            return False
        if receipt.get("status") == "unavailable":
            return set(receipt) == {"schema_version", "status", "reason"} and receipt["reason"] in REASONS
        if set(receipt) != {"schema_version", "status", "events", "truncated"} or receipt["status"] != "available":
            return False
        events = receipt["events"]
        return (
            type(receipt["truncated"]) is bool and isinstance(events, list) and len(events) <= MAX_EVENTS
            and all(_valid_event(event, allowed_apps()) for event in events)
            and [event["seconds_after_since"] for event in events]
            == sorted((event["seconds_after_since"] for event in events), reverse=True)
        )
    except Exception:
        return False


def write_receipt(destination: Path, receipt: object) -> bool:
    """Refuse invalid data before creating a file; I/O failure stays advisory."""
    try:
        if not validate_receipt(receipt):
            return False
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(receipt, ensure_ascii=True, indent=2) + "\n", encoding="ascii")
        return True
    except Exception:
        return False


def main(argv: list[str] | None = None) -> int:
    try:
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument("--since", required=True)
        parser.add_argument("--output", required=True, type=Path)
        args = parser.parse_args(argv)
        write_receipt(args.output, collect(args.since))
    except (Exception, SystemExit):
        pass  # This optional evidence must never replace the qualification outcome.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
