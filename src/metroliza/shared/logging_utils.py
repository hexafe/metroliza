"""Utilities for resolving and applying application-wide logging configuration.

This module centralizes environment-driven log level resolution and handler setup
for Metroliza's root logger, including rotating file sinks and optional console
output.
"""

import base64
import binascii
import json
import logging
import logging.handlers
import os
import re
import sys
import tempfile
import threading
from collections import defaultdict, deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from itertools import islice
from pathlib import Path
from types import TracebackType
from typing import Any, Callable, Self, SupportsIndex, cast, overload

from metroliza.shared.env_utils import parse_bool


LOG_FILE_NAME = "metroliza.log"
_GLOBAL_LEVEL_ENV = "METROLIZA_LOG_LEVEL"
_FILE_LEVEL_ENV = "METROLIZA_FILE_LOG_LEVEL"
_CONSOLE_LEVEL_ENV = "METROLIZA_CONSOLE_LOG_LEVEL"
_SUPPORT_BUILD_ENV = "METROLIZA_SUPPORT_BUILD"
_FILE_MAX_BYTES = 10 * 1024 * 1024
_FILE_BACKUP_COUNT = 7
_REDACTED = "[REDACTED]"
_MAX_EXCEPTION_CHAIN_DEPTH = 32
_MAX_EXCEPTION_GROUP_NODES = 128
_MAX_EXCEPTION_NOTES = 128
_MAX_EXCEPTION_METADATA_ITEMS = 128
_MAX_ARGUMENT_CONTAINER_ITEMS = 128
_MAX_ARGUMENT_TRAVERSAL_ITEMS = 4096
_MAX_LOG_TEXT_CHARACTERS = 65536
_MAX_LOG_RECORD_EXTRAS = 128
_MAX_BUFFERED_LOG_RECORDS = 128
_MAX_LOG_FORMAT_FIELD_CHARACTERS = 4096
_MAX_LOG_INTEGER_BITS = 16384
_MAX_TRACEBACK_FRAMES = 4096
_MAX_CANONICALIZATION_PASSES = 8
_MAX_CANONICALIZATION_CHARACTERS = (
    _MAX_LOG_TEXT_CHARACTERS * _MAX_CANONICALIZATION_PASSES * 2
)
_CONFIGURATION_LOCK = threading.RLock()
_LOGGING_MODULE_LOCK = cast(Any, logging)._lock


class _TracebackNotProvided:
    __slots__ = ()


_TRACEBACK_NOT_PROVIDED = _TracebackNotProvided()

_PRIVATE_KEY_BLOCK_PATTERN = re.compile(
    r"-----BEGIN(?: [A-Z0-9]+)* PRIVATE KEY(?: BLOCK)?-----[\s\S]*",
    re.IGNORECASE,
)
_PUTTY_PRIVATE_KEY_PATTERN = re.compile(
    r"PuTTY-User-Key-File-[0-9]+:[^\r\n]*[\s\S]*",
    re.IGNORECASE,
)
_SSH2_PRIVATE_KEY_PATTERN = re.compile(
    r"---- BEGIN SSH2(?: ENCRYPTED)? PRIVATE KEY ----[\s\S]*",
    re.IGNORECASE,
)
_AGE_PRIVATE_KEY_PATTERN = re.compile(
    r"AGE-SECRET-KEY-1[^\r\n]*[\s\S]*",
    re.IGNORECASE,
)
_PRIVATE_KEY_DATA_MEDIA_TYPES = frozenset(
    {
        "application/pkcs8",
        "application/pkcs8-encrypted",
        "application/x-pkcs8",
        "application/x-pkcs8-encrypted",
        "application/pkcs12",
        "application/x-pkcs12",
        "application/pfx",
    }
)
_JWK_DATA_MEDIA_TYPES = frozenset(
    {"application/jwk+json", "application/jwk-set+json"}
)
_JWK_KTY_PATTERN = re.compile(
    r'''"kty"\s*:\s*"(?P<kty>RSA|EC|OKP|oct)"''',
    re.IGNORECASE,
)
_JWK_PRIVATE_D_PATTERN = re.compile(r'''"d"\s*:\s*"[^"]+"''')
_JWK_PRIVATE_K_PATTERN = re.compile(r'''"k"\s*:\s*"[^"]+"''')
_AUTHORIZATION_PATTERN = re.compile(
    r'''(?isx)
    \b(?P<prefix>(?:proxy[_ -]?)?authorization\s*[:=]\s*)
    (?P<value>[\s\S]*)
    ''',
)
_BEARER_PATTERN = re.compile(r"\b(bearer\s+)([^\s,;]+)", re.IGNORECASE)
_CONNECTION_VALUE_PATTERN = re.compile(
    r"(?is)\b(?P<prefix>(?:dsn|connection(?:[_ -]?string)?)\s*[:=]\s*)(?P<value>[\s\S]*)",
)
_COMPOUND_CREDENTIAL_VALUE_PATTERN = re.compile(
    r'''(?isx)
    \b(?P<prefix>
        (?:(?:api|private|secret)[_ -]+key|password[_ -]+hash)
        \s*[:=]\s*
    )
    (?P<value>[\s\S]*)
    ''',
)
_WHITESPACE_CREDENTIAL_PATTERN = re.compile(
    r'''(?isx)
    (?<![A-Za-z0-9_-])
    (?P<prefix>
        (?:
            --(?:password|passwd|passphrase|token|secret|api[-_]?key|private[-_]?key)|
            requirepass|
            identityfile|
            machine\s+\S+\s+login\s+\S+\s+password
        )\s+
    )
    (?P<value>[\s\S]+)
    ''',
)
_CAMEL_CASE_BOUNDARY_PATTERN = re.compile(
    r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])"
)
_NON_IDENTIFIER_PATTERN = re.compile(r"[^A-Za-z0-9]+")
_JSON_LABEL_ESCAPE_PATTERN = re.compile(
    r'''\\(u[0-9A-Fa-f]{4}|["\\/bfnrt])'''
)
_FORM_PERCENT_ESCAPE_PATTERN = re.compile(r"%([0-9A-Fa-f]{2})")
_CREDENTIAL_LABEL_SUFFIXES = (
    "password",
    "passwd",
    "pwd",
    "passphrase",
    "token",
    "secret",
    "credential",
    "credentials",
    "authorization",
    "authentication",
    "cookie",
    "cookies",
    "apikey",
    "privatekey",
    "secretkey",
    "passwordhash",
    "dsn",
    "connectionstring",
)
_CREDENTIAL_EXACT_LABELS = frozenset({"pass", "dbpass", "userpass"})
_SAFE_CREDENTIAL_LABEL_PREFIXES = frozenset(
    {
        "access",
        "api",
        "bearer",
        "client",
        "db",
        "private",
        "proxy",
        "refresh",
        "session",
        "user",
    }
)
_SENSITIVE_CONTENT_COMPACT_LABELS = frozenset(
    {
        "query",
        "dbquery",
        "sqlquery",
        "sqltext",
        "sqlstatement",
        "source",
        "dbsource",
        "sourcepath",
        "sourcetext",
        "sourcecode",
        "path",
        "pathname",
        "filepath",
        "sensitivepath",
        "secretpath",
        "credentialpath",
        "passwordpath",
        "tokenpath",
        "apikeypath",
        "clientsecretpath",
        "accesstokenpath",
        "refreshtokenpath",
        "statement",
        "dbstatement",
        "clientkey",
        "clientkeydata",
        "sslkey",
        "tlskey",
        "identityfile",
        "accountkey",
        "sharedaccesskey",
        "sharedaccesssignature",
    }
)
_SENSITIVE_CONTENT_PATTERN = re.compile(
    r'''(?isx)
    \b(?P<prefix>
        (?:
            sql(?:[_ -]?(?:query|text|statement))?|query|
            source(?:[_ -]?(?:text|path|code))?|file[_ -]?path|path|
            (?:
                sensitive|secret|credentials?|password|token|api[_-]?key|
                client[_-]?secret|access[_-]?token|refresh[_-]?token
            )[_ -]?path
        )\s*[:=]\s*
    )
    (?P<value>[\s\S]*)
    ''',
)
_SAFE_EXCEPTION_TYPE_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
_SENSITIVE_ARGUMENT_KEY_PATTERN = re.compile(
    r'''(?ix)
    (?<![A-Za-z0-9])
    (?:
        password|passwd|pwd|passphrase|token|api[_ -]?key|private[_ -]?key|
        access[_ -]?token|refresh[_ -]?token|client[_ -]?secret|secret|
        credentials?|auth(?:entication)?|authorization|cookies?|dsn|
        connection(?:[_ -]?string)?|sql(?:[_ -]?(?:query|text|statement))?|
        query|source|path|pathname
    )
    (?![A-Za-z0-9])
    ''',
)
_LOG_RECORD_CORE_FIELDS = frozenset(
    {
        "args",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "message",
        "module",
        "msecs",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "taskName",
        "thread",
        "threadName",
        "_metroliza_exception_summary",
        "_metroliza_stack_summary",
    }
)
_SENSITIVE_LOG_RECORD_CORE_FIELDS = frozenset(
    {"filename", "funcName", "module", "pathname"}
)


@dataclass(frozen=True)
class LoggingConfig:
    """Resolved logging levels for global, file, and console handlers.

    Attributes:
        global_level: Root logger level that gates all log records.
        file_level: Per-file-handler threshold for persisted logs.
        console_level: Stream handler threshold, or ``None`` to disable
            console logging.
    """

    global_level: int
    file_level: int
    console_level: int | None


@dataclass
class _ArgumentSanitizationState:
    seen: set[int]
    remaining_items: int = _MAX_ARGUMENT_TRAVERSAL_ITEMS
    remaining_characters: int = _MAX_LOG_TEXT_CHARACTERS


@dataclass(frozen=True)
class _ExceptionGroupSummary:
    text: str
    traceback_count: int = 0
    traceback_truncated: bool = False
    traceback_unknown: bool = False
    note_count: int = 0
    notes_truncated: bool = False
    notes_unknown: bool = False
    cause_edges: int = 0
    context_edges: int = 0
    edge_unknown: bool = False


class _JsonObjectPairs(list[tuple[object, object]]):
    """Keep JSON object member order and duplicates for bounded inspection."""


class _MissingTypeMember:
    __slots__ = ()


_MISSING_TYPE_MEMBER = _MissingTypeMember()


class _UnsupportedScalar:
    __slots__ = ()


_UNSUPPORTED_SCALAR = _UnsupportedScalar()


def _is_actual_instance(value: object, base_type: type[object]) -> bool:
    """Check the real type without consulting an object's ``__class__`` hook."""
    return issubclass(type(value), base_type)


def _handler_values(handler: logging.Handler) -> dict[str, Any] | None:
    try:
        descriptor = logging.Filterer.__dict__["__dict__"]
        values = descriptor.__get__(handler, type(handler))
    except BaseException:
        return None
    return cast(dict[str, Any], values) if type(values) is dict else None


def _type_member_without_metaclass_hooks(value: object, name: str) -> object:
    """Resolve a raw class member without invoking a custom metaclass."""
    try:
        value_type = type(value)
        method_resolution_order = type.__getattribute__(value_type, "__mro__")
        for candidate_type in method_resolution_order:
            namespace = type.__getattribute__(candidate_type, "__dict__")
            if name in namespace:
                return namespace[name]
    except BaseException:
        return _MISSING_TYPE_MEMBER
    return _MISSING_TYPE_MEMBER


def _redact_to_end(match: re.Match[str]) -> str:
    return f"{match.group('prefix')}{_REDACTED}"


def _is_ascii_uri_scheme_character(character: str) -> bool:
    return character.isascii() and (
        character.isalnum() or character in "+-."
    )


def _json_slash_token_end(text: str, index: int) -> int | None:
    if text.startswith("/", index):
        return index + 1
    if text.startswith("\\/", index):
        return index + 2
    if text[index : index + 6].casefold() == "\\u002f":
        return index + 6
    return None


def _double_slash_end(text: str, index: int) -> int | None:
    first_end = _json_slash_token_end(text, index)
    if first_end is None:
        return None
    return _json_slash_token_end(text, first_end)


def _uri_prefix_end(text: str, index: int) -> tuple[int | None, int]:
    network_path_end = _double_slash_end(text, index)
    if network_path_end is not None and (
        index == 0 or text[index - 1] not in ":/"
    ):
        return network_path_end, network_path_end

    character = text[index]
    if not (character.isascii() and character.isalpha()):
        return None, index + 1
    if index > 0 and (text[index - 1].isalnum() or text[index - 1] == "_"):
        return None, index + 1

    cursor = index + 1
    while cursor < len(text) and _is_ascii_uri_scheme_character(text[cursor]):
        cursor += 1
    if cursor < len(text) and text[cursor] == ":":
        absolute_path_end = _double_slash_end(text, cursor + 1)
        if absolute_path_end is not None:
            return absolute_path_end, absolute_path_end
    return None, max(index + 1, cursor)


def _uri_delimiter_end(text: str, index: int) -> int | None:
    character = text[index]
    if character in "/?#":
        return index + 1
    if text.startswith("\\/", index):
        return index + 2
    encoded = text[index : index + 6].casefold()
    if encoded in {"\\u002f", "\\u003f", "\\u0023"}:
        return index + 6
    return None


def _uri_userinfo_end(text: str, start: int) -> tuple[int | None, int]:
    cursor = start
    while cursor < len(text):
        character = text[cursor]
        if character == "@":
            return (cursor if cursor > start else None), cursor + 1
        if text[cursor : cursor + 6].casefold() == "\\u0040":
            return (cursor if cursor > start else None), cursor + 6
        if _uri_delimiter_end(text, cursor) is not None or character.isspace():
            return None, cursor
        cursor += 1
    return None, cursor


def _redact_credential_uris(text: str) -> str:
    pieces: list[str] = []
    output_cursor = 0
    index = 0

    while index < len(text):
        prefix_end, next_index = _uri_prefix_end(text, index)
        if prefix_end is None:
            index = next_index
            continue

        userinfo_end, scan_end = _uri_userinfo_end(text, prefix_end)
        if userinfo_end is None:
            index = max(index + 1, scan_end)
            continue

        pieces.extend(
            (
                text[output_cursor:prefix_end],
                _REDACTED,
                text[userinfo_end:scan_end],
            )
        )
        output_cursor = scan_end
        index = output_cursor

    if not pieces:
        return text
    pieces.append(text[output_cursor:])
    return "".join(pieces)


def _sip_prefix_end(text: str, index: int) -> int | None:
    if index > 0 and (text[index - 1].isalnum() or text[index - 1] == "_"):
        return None
    prefix = text[index : index + 5].casefold()
    if prefix.startswith("sips:"):
        return index + 5
    if prefix.startswith("sip:"):
        return index + 4
    return None


def _redact_sip_credentials(text: str) -> str:
    pieces: list[str] = []
    output_cursor = 0
    index = 0

    while index < len(text):
        prefix_end = _sip_prefix_end(text, index)
        if prefix_end is None:
            index += 1
            continue
        userinfo_end, scan_end = _uri_userinfo_end(text, prefix_end)
        if userinfo_end is None:
            index = max(index + 1, scan_end)
            continue
        userinfo = text[prefix_end:userinfo_end]
        separator = userinfo.find(":")
        if separator < 0:
            separator = userinfo.casefold().find("\\u003a")
            separator_width = 6
        else:
            separator_width = 1
        if separator < 0 or separator + separator_width == len(userinfo):
            index = scan_end
            continue
        pieces.extend(
            (
                text[output_cursor:prefix_end],
                _REDACTED,
                text[userinfo_end:scan_end],
            )
        )
        output_cursor = scan_end
        index = output_cursor

    if not pieces:
        return text
    pieces.append(text[output_cursor:])
    return "".join(pieces)


def _quoted_assignment_can_start(
    text: str,
    segment_start: int,
    cursor: int,
) -> bool:
    return text[cursor] in "\"'" and (
        cursor == segment_start
        or cursor == 0
        or text[cursor - 1].isspace()
        or text[cursor - 1] in "{[,("
    )


def _quoted_assignment_bounds(
    text: str,
    cursor: int,
) -> tuple[int, int, int] | None:
    quote = text[cursor]
    quoted_cursor = cursor + 1
    quote_escaped = False
    while quoted_cursor < len(text):
        quoted_character = text[quoted_cursor]
        if quote_escaped:
            quote_escaped = False
        elif quoted_character == "\\":
            quote_escaped = True
        elif quoted_character == quote:
            break
        quoted_cursor += 1
    separator = quoted_cursor + 1
    while separator < len(text) and text[separator].isspace():
        separator += 1
    if (
        quoted_cursor >= len(text)
        or separator >= len(text)
        or text[separator] not in ":="
    ):
        return None
    separator_end = separator + 1
    while separator_end < len(text) and text[separator_end].isspace():
        separator_end += 1
    return quoted_cursor, separator, separator_end


def _unquoted_assignment_bounds(
    text: str,
    segment_start: int,
    separator: int,
) -> tuple[int, int, int]:
    label_end = separator
    while label_end > segment_start and text[label_end - 1].isspace():
        label_end -= 1
    label_start = label_end
    while label_start > segment_start and _is_form_key_character(
        text[label_start - 1]
    ):
        label_start -= 1
    separator_end = separator + 1
    while separator_end < len(text) and text[separator_end].isspace():
        separator_end += 1
    return label_start, label_end, separator_end


def _redact_sensitive_assignment(text: str) -> str:
    segment_start = 0
    cursor = 0
    while cursor < len(text):
        character = text[cursor]
        if _quoted_assignment_can_start(text, segment_start, cursor):
            quote = character
            bounds = _quoted_assignment_bounds(text, cursor)
            if bounds is not None:
                quoted_cursor, separator, separator_end = bounds
                label = text[cursor + 1 : quoted_cursor]
                if _is_sensitive_label(label):
                    safe_label = _safe_sensitive_label_for_output(label)
                    return (
                        f"{text[:cursor]}{quote}{safe_label}{quote}"
                        f"{text[quoted_cursor + 1 : separator_end]}{_REDACTED}"
                    )
                segment_start = separator + 1
                cursor = separator + 1
                continue
        if character not in ":=":
            cursor += 1
            continue
        label_start, label_end, separator_end = _unquoted_assignment_bounds(
            text,
            segment_start,
            cursor,
        )
        label = text[label_start:label_end]
        if label_start < label_end and _is_sensitive_label(label):
            safe_label = _safe_sensitive_label_for_output(label)
            return (
                f"{text[:label_start]}{safe_label}"
                f"{text[label_end:separator_end]}{_REDACTED}"
            )

        segment_start = cursor + 1
        cursor += 1
    return text


def _json_contains_private_jwk(value: object) -> tuple[bool, bool]:
    pending: list[object] = [value]

    while pending:
        item = pending.pop()

        if type(item) is _JsonObjectPairs:
            pairs = item
            key_types: set[str] = set()
            member_names: set[str] = set()
            for key, member in pairs:
                if type(key) is str:
                    normalized_key = key.casefold()
                    member_names.add(normalized_key)
                    if normalized_key == "kty" and type(member) is str:
                        key_types.add(member.casefold())
                pending.append(member)
            if ("oct" in key_types and "k" in member_names) or (
                key_types.intersection({"rsa", "ec", "okp"})
                and "d" in member_names
            ):
                return True, False
        elif type(item) is list:
            members = cast(list[object], item)
            pending.extend(members)

    return False, False


def _redact_private_jwk(text: str) -> str:
    try:
        parsed = json.loads(text, object_pairs_hook=_JsonObjectPairs)
    except (MemoryError, RecursionError):
        return _REDACTED
    except (TypeError, ValueError):
        parsed = None
    else:
        contains_private_jwk, inspection_truncated = _json_contains_private_jwk(parsed)
        if contains_private_jwk or inspection_truncated:
            return _REDACTED

    decoded_text = _JSON_LABEL_ESCAPE_PATTERN.sub(
        _decode_json_label_escape,
        text,
    )
    key_types = {
        match.group("kty").casefold()
        for match in _JWK_KTY_PATTERN.finditer(decoded_text)
    }
    if (
        "oct" in key_types
        and _JWK_PRIVATE_K_PATTERN.search(decoded_text) is not None
    ) or (
        key_types.intersection({"rsa", "ec", "okp"})
        and _JWK_PRIVATE_D_PATTERN.search(decoded_text) is not None
    ):
        return _REDACTED
    return text


def _redact_signing_private_key(text: str) -> str:
    folded = text.casefold()
    prefix = "untrusted comment:"
    search_start = 0
    while search_start < len(text):
        header_start = folded.find(prefix, search_start)
        if header_start < 0:
            return text
        carriage_return = folded.find("\r", header_start)
        line_feed = folded.find("\n", header_start)
        line_end_candidates = [
            index for index in (carriage_return, line_feed) if index >= 0
        ]
        line_end = min(line_end_candidates, default=len(text))
        header = folded[header_start:line_end]
        if (
            "secret key" in header
            and ("minisign" in header or "signify" in header)
        ):
            return f"{text[:header_start]}{_REDACTED}"
        search_start = line_end + 1
    return text


def _decode_json_label_escape(match: re.Match[str]) -> str:
    escape = match.group(1)
    if escape.startswith("u"):
        return chr(int(escape[1:], 16))
    return {
        '"': '"',
        "\\": "\\",
        "/": "/",
        "b": " ",
        "f": " ",
        "n": " ",
        "r": " ",
        "t": " ",
    }[escape]


def _decode_form_percent_escape(match: re.Match[str]) -> str:
    return chr(int(match.group(1), 16))


def _decode_form_component(value: str) -> str:
    return _FORM_PERCENT_ESCAPE_PATTERN.sub(
        _decode_form_percent_escape,
        value.replace("+", " "),
    )


def _canonicalize_encoded_log_text(value: str) -> tuple[str, bool]:
    """Decode composed JSON/form escaping with explicit work bounds.

    The boolean result reports an exhausted depth or character budget. Callers
    fail closed when inspection could not reach a stable representation.
    """
    current = value
    remaining_characters = _MAX_CANONICALIZATION_CHARACTERS
    for _ in range(_MAX_CANONICALIZATION_PASSES):
        remaining_characters -= len(current) * 2
        if remaining_characters < 0:
            return current, True
        decoded = _JSON_LABEL_ESCAPE_PATTERN.sub(
            _decode_json_label_escape,
            current,
        )
        decoded = _decode_form_component(decoded)
        if decoded == current:
            return current, False
        current = decoded
    probe = _JSON_LABEL_ESCAPE_PATTERN.sub(
        _decode_json_label_escape,
        current,
    )
    probe = _decode_form_component(probe)
    return current, probe != current


def _jwk_data_payload_is_private(metadata: str, payload: str) -> bool:
    metadata_tokens = metadata.casefold().split(";")
    if "base64" in metadata_tokens:
        try:
            decoded_payload = base64.b64decode(
                payload.encode("ascii"),
                validate=True,
            ).decode("utf-8")
        except (UnicodeError, ValueError, binascii.Error):
            return True
    else:
        decoded_payload = _decode_form_component(payload)
    try:
        parsed = json.loads(decoded_payload, object_pairs_hook=_JsonObjectPairs)
    except (MemoryError, RecursionError, TypeError, ValueError):
        return True
    contains_private_jwk, inspection_truncated = _json_contains_private_jwk(parsed)
    return contains_private_jwk or inspection_truncated


def _redact_private_data_uris(text: str) -> str:
    folded = text.casefold()
    prefix = "data:application/"
    search_start = 0

    while search_start < len(text):
        data_start = folded.find(prefix, search_start)
        if data_start < 0:
            return text
        metadata_start = data_start + len("data:")
        cursor = metadata_start
        next_candidate: int | None = None
        while cursor < len(text):
            if cursor > metadata_start and folded.startswith("data:", cursor):
                next_candidate = cursor
                break
            character = text[cursor]
            if character == "," or character.isspace():
                break
            cursor += 1
        if next_candidate is not None:
            search_start = next_candidate
            continue
        if cursor >= len(text) or text[cursor] != ",":
            search_start = max(data_start + 1, cursor + 1)
            continue

        metadata = folded[metadata_start:cursor]
        media_type = metadata.split(";", 1)[0]
        payload = text[cursor + 1 :]
        if media_type in _PRIVATE_KEY_DATA_MEDIA_TYPES or (
            media_type in _JWK_DATA_MEDIA_TYPES
            and _jwk_data_payload_is_private(metadata, payload)
        ):
            return f"{text[:data_start]}{_REDACTED}"
        search_start = cursor + 1

    return text


def _is_form_key_character(character: str) -> bool:
    return character.isascii() and (
        character.isalnum() or character in "_.[]/%+-"
    )


def _redact_form_pairs(text: str) -> str:
    pieces: list[str] = []
    output_cursor = 0
    search_start = 0
    while search_start < len(text):
        separator = text.find("=", search_start)
        if separator < 0:
            break

        key_start = separator
        while key_start > search_start and _is_form_key_character(
            text[key_start - 1]
        ):
            key_start -= 1
        if key_start == separator:
            search_start = separator + 1
            continue

        value_start = separator + 1
        value_end = value_start
        while value_end < len(text):
            character = text[value_end]
            if character == "&" or character.isspace():
                break
            value_end += 1

        decoded_key = _decode_form_component(text[key_start:separator])
        decoded_value = _decode_form_component(text[value_start:value_end])
        decoded_redacted = _redact_non_form_text(decoded_value)
        if not (
            _is_sensitive_label(decoded_key)
            or decoded_redacted != decoded_value
        ):
            search_start = value_end
            continue
        pieces.extend((text[output_cursor:value_start], _REDACTED))
        output_cursor = value_end
        search_start = value_end
    if not pieces:
        return text
    pieces.append(text[output_cursor:])
    return "".join(pieces)


def _is_sensitive_label(label: str) -> bool:
    decoded_label, inspection_truncated = _canonicalize_encoded_log_text(
        label.strip()
    )
    if inspection_truncated:
        return True
    normalized = _CAMEL_CASE_BOUNDARY_PATTERN.sub("_", decoded_label)
    if _SENSITIVE_ARGUMENT_KEY_PATTERN.search(normalized) is not None:
        return True
    normalized_parts = _NON_IDENTIFIER_PATTERN.split(normalized)
    if any(
        part.casefold() in _CREDENTIAL_EXACT_LABELS
        or part.casefold().endswith(_CREDENTIAL_LABEL_SUFFIXES)
        or part.casefold() in _SENSITIVE_CONTENT_COMPACT_LABELS
        for part in normalized_parts
        if part
    ):
        return True
    compact = _NON_IDENTIFIER_PATTERN.sub("", normalized).casefold()
    return (
        compact in _CREDENTIAL_EXACT_LABELS
        or compact.endswith(_CREDENTIAL_LABEL_SUFFIXES)
        or compact in _SENSITIVE_CONTENT_COMPACT_LABELS
    )


def _safe_sensitive_label_for_output(label: str) -> str:
    decoded_label, inspection_truncated = _canonicalize_encoded_log_text(
        label.strip()
    )
    if inspection_truncated:
        return _REDACTED
    normalized = _CAMEL_CASE_BOUNDARY_PATTERN.sub("_", decoded_label)
    compact = _NON_IDENTIFIER_PATTERN.sub("", normalized).casefold()
    if (
        compact in _CREDENTIAL_EXACT_LABELS
        or compact in _SENSITIVE_CONTENT_COMPACT_LABELS
        or compact == "auth"
    ):
        return label
    for suffix in _CREDENTIAL_LABEL_SUFFIXES:
        if not compact.endswith(suffix):
            continue
        prefix = compact[: -len(suffix)]
        if not prefix or prefix in _SAFE_CREDENTIAL_LABEL_PREFIXES:
            return label
    return _REDACTED


def _private_jwk_mapping_member_names(value: dict[object, object]) -> set[str]:
    key_types: set[str] = set()
    key_type_unknown = False
    inspection_truncated = len(value) > _MAX_ARGUMENT_CONTAINER_ITEMS
    for candidate_key, candidate_value in islice(
        value.items(),
        _MAX_ARGUMENT_CONTAINER_ITEMS + 1,
    ):
        if type(candidate_key) is not str:
            key_type_unknown = True
            continue
        if candidate_key.casefold() != "kty":
            continue
        if type(candidate_value) is str:
            key_types.add(candidate_value.casefold())
        else:
            key_type_unknown = True
    private_member_names: set[str] = set()
    if "oct" in key_types or key_type_unknown or inspection_truncated:
        private_member_names.add("k")
    if (
        key_types.intersection({"rsa", "ec", "okp"})
        or key_type_unknown
        or inspection_truncated
    ):
        private_member_names.add("d")
    return private_member_names


def _sanitize_mapping_argument(
    value: dict[object, object],
    *,
    depth: int,
    state: _ArgumentSanitizationState,
) -> dict[object, object]:
    sanitized: dict[object, object] = {}
    jwk_private_member_names = _private_jwk_mapping_member_names(value)

    for key, item in islice(value.items(), _MAX_ARGUMENT_CONTAINER_ITEMS):
        if type(key) is not str:
            safe_key: object = "[REDACTED]; nonstandard_mapping_key=present"
            safe_item: object = _REDACTED
        else:
            jwk_sensitive_key = key.casefold() in jwk_private_member_names
            bounded_key = cast(
                str,
                _sanitize_log_value(key, depth=depth + 1, state=state),
            )
            sensitive_key = jwk_sensitive_key or _is_sensitive_label(bounded_key)
            safe_key = _REDACTED if sensitive_key else redact_log_text(bounded_key)
            safe_item = (
                _REDACTED
                if sensitive_key
                else _sanitize_log_value(item, depth=depth + 1, state=state)
            )
        try:
            sanitized[safe_key] = safe_item
        except TypeError:
            sanitized["[REDACTED]; invalid_mapping_key=present"] = safe_item
    if len(value) > _MAX_ARGUMENT_CONTAINER_ITEMS:
        sanitized["argument_items_truncated"] = True
    return sanitized


def _sanitize_builtin_container(
    value: object,
    *,
    depth: int,
    state: _ArgumentSanitizationState,
) -> object:
    if type(value) in (dict, defaultdict):
        mapping_value = cast(dict[object, object], value)
        return _sanitize_mapping_argument(mapping_value, depth=depth, state=state)
    if type(value) is list:
        list_value = cast(list[object], value)
        sanitized_list = [
            _sanitize_log_value(item, depth=depth + 1, state=state)
            for item in list_value[:_MAX_ARGUMENT_CONTAINER_ITEMS]
        ]
        if len(list_value) > _MAX_ARGUMENT_CONTAINER_ITEMS:
            sanitized_list.append("argument_items_truncated=present")
        return sanitized_list
    if type(value) is tuple:
        tuple_value = cast(tuple[object, ...], value)
        sanitized_tuple = tuple(
            _sanitize_log_value(item, depth=depth + 1, state=state) for item in tuple_value
            [:_MAX_ARGUMENT_CONTAINER_ITEMS]
        )
        if len(tuple_value) > _MAX_ARGUMENT_CONTAINER_ITEMS:
            return (*sanitized_tuple, "argument_items_truncated=present")
        return sanitized_tuple
    collection_name = "set" if type(value) is set else "frozenset"
    collection_size = len(cast(set[object] | frozenset[object], value))
    return f"container_type={collection_name}; item_count={collection_size}; values=[REDACTED]"


def _sanitize_log_value(
    value: object,
    *,
    depth: int = 0,
    state: _ArgumentSanitizationState | None = None,
) -> object:
    active_state = (
        _ArgumentSanitizationState(set()) if state is None else state
    )
    if active_state.remaining_items <= 0:
        return "[REDACTED]; argument_item_limit=present"
    active_state.remaining_items -= 1

    if _is_actual_instance(value, BaseException):
        try:
            return summarize_exception(cast(BaseException, value))
        except BaseException:
            return "exception_type=Exception; traceback=unknown; chain=unknown"

    if type(value) in (str, bytes):
        return _sanitize_text_log_value(cast(str | bytes, value), active_state)

    sanitized_scalar = _sanitize_scalar_log_value(value)
    if sanitized_scalar is not _UNSUPPORTED_SCALAR:
        return sanitized_scalar

    container_types = (dict, defaultdict, list, tuple, set, frozenset)
    if type(value) not in container_types:
        object_type = _safe_exception_type_name(type(value))
        return f"object_type={object_type}; object_value=[REDACTED]"
    if depth >= 16:
        return "[REDACTED]; argument_depth_limit=present"

    if id(value) in active_state.seen:
        return "[REDACTED]; repeated_argument=present"
    active_state.seen.add(id(value))
    return _sanitize_builtin_container(value, depth=depth, state=active_state)


def _sanitize_text_log_value(
    value: str | bytes,
    state: _ArgumentSanitizationState,
) -> str:
    available = max(0, state.remaining_characters)
    if len(value) > available:
        state.remaining_characters = 0
        kind = "text" if type(value) is str else "bytes"
        return f"[REDACTED]; argument_{kind}_truncated=present"
    state.remaining_characters -= len(value)
    return redact_log_text(value if type(value) is str else repr(value))


def _sanitize_scalar_log_value(value: object) -> object:
    if type(value) is int:
        return value if value.bit_length() <= _MAX_LOG_INTEGER_BITS else 0
    if type(value) in (float, bool, complex, type(None)):
        return value
    if not _is_actual_instance(value, int):
        return _UNSUPPORTED_SCALAR
    integer_value = int.__int__(cast(int, value))
    return integer_value if integer_value.bit_length() <= _MAX_LOG_INTEGER_BITS else 0


def _redact_record_arguments(
    arguments: tuple[object, ...] | Mapping[str, object] | None,
    *,
    state: _ArgumentSanitizationState | None = None,
) -> tuple[object, ...] | Mapping[str, object] | None:
    if arguments is None:
        return arguments
    try:
        sanitized = _sanitize_log_value(arguments, state=state)
    except BaseException:
        return {}
    if type(arguments) in (dict, defaultdict):
        return (
            cast(Mapping[str, object], sanitized)
            if type(sanitized) is dict
            else {}
        )
    return cast(tuple[object, ...], sanitized) if type(sanitized) is tuple else ()


def _sanitize_message_template(
    value: object,
    state: _ArgumentSanitizationState,
) -> tuple[object, bool]:
    if type(value) is not str:
        return _sanitize_log_value(value, state=state), False
    if state.remaining_items <= 0:
        return "[REDACTED]; argument_item_limit=present", False
    state.remaining_items -= 1
    available = max(0, state.remaining_characters)
    if len(value) > available:
        state.remaining_characters = 0
        return "[REDACTED]; argument_text_truncated=present", False
    state.remaining_characters -= len(value)
    return value, True


def _append_bounded_log_text(
    pieces: list[str],
    value: str,
    output_length: int,
) -> int:
    new_length = output_length + len(value)
    if new_length > _MAX_LOG_TEXT_CHARACTERS:
        raise OverflowError("bounded log formatting exceeded output limit")
    pieces.append(value)
    return new_length


def _bounded_decimal_field_value(template: str, start: int) -> tuple[int, int]:
    cursor = start
    value = 0
    while cursor < len(template) and template[cursor].isdigit():
        value = value * 10 + int(template[cursor])
        if value > _MAX_LOG_FORMAT_FIELD_CHARACTERS:
            raise OverflowError("log format field exceeds width limit")
        cursor += 1
    return value, cursor


@dataclass(frozen=True)
class _PercentFormatField:
    mapping_key: str | None
    specification: str
    dynamic_values: tuple[int, ...]
    next_cursor: int
    next_positional_index: int


def _parse_percent_mapping_key(
    template: str,
    start: int,
) -> tuple[str | None, int]:
    if start >= len(template) or template[start] != "(":
        return None, start
    key_start = start + 1
    cursor = key_start
    parenthesis_depth = 1
    while cursor < len(template) and parenthesis_depth > 0:
        if template[cursor] == "(":
            parenthesis_depth += 1
        elif template[cursor] == ")":
            parenthesis_depth -= 1
            if parenthesis_depth == 0:
                break
        cursor += 1
    if cursor >= len(template) or parenthesis_depth != 0:
        raise ValueError("malformed mapping field")
    return template[key_start:cursor], cursor + 1


def _bounded_dynamic_percent_value(
    positional_arguments: tuple[object, ...] | None,
    positional_index: int,
    field_name: str,
) -> tuple[int, int]:
    if positional_arguments is None:
        raise TypeError(f"dynamic {field_name} requires positional arguments")
    if positional_index >= len(positional_arguments):
        raise TypeError(f"dynamic {field_name} argument is missing")
    value = positional_arguments[positional_index]
    if type(value) is bool:
        value = int(value)
    if type(value) is not int or abs(value) > _MAX_LOG_FORMAT_FIELD_CHARACTERS:
        raise OverflowError(f"dynamic log format {field_name} exceeds limit")
    return value, positional_index + 1


def _parse_percent_width(
    template: str,
    start: int,
    mapping_key: str | None,
    positional_arguments: tuple[object, ...] | None,
    positional_index: int,
) -> tuple[int, tuple[int, ...], int]:
    cursor = start
    while cursor < len(template) and template[cursor] in "#0- +":
        cursor += 1
    if cursor >= len(template) or template[cursor] != "*":
        _, cursor = _bounded_decimal_field_value(template, cursor)
        return cursor, (), positional_index
    if mapping_key is not None:
        raise TypeError("dynamic width requires positional arguments")
    value, positional_index = _bounded_dynamic_percent_value(
        positional_arguments,
        positional_index,
        "width",
    )
    return cursor + 1, (value,), positional_index


def _parse_percent_precision(
    template: str,
    start: int,
    mapping_key: str | None,
    positional_arguments: tuple[object, ...] | None,
    positional_index: int,
) -> tuple[int, tuple[int, ...], int]:
    if start >= len(template) or template[start] != ".":
        return start, (), positional_index
    cursor = start + 1
    if cursor >= len(template) or template[cursor] != "*":
        _, cursor = _bounded_decimal_field_value(template, cursor)
        return cursor, (), positional_index
    if mapping_key is not None:
        raise TypeError("dynamic precision requires positional arguments")
    value, positional_index = _bounded_dynamic_percent_value(
        positional_arguments,
        positional_index,
        "precision",
    )
    return cursor + 1, (value,), positional_index


def _parse_percent_field(
    template: str,
    percent_cursor: int,
    positional_arguments: tuple[object, ...] | None,
    positional_index: int,
) -> _PercentFormatField:
    mapping_key, cursor = _parse_percent_mapping_key(
        template,
        percent_cursor + 1,
    )
    format_body_start = cursor
    cursor, width_values, positional_index = _parse_percent_width(
        template,
        cursor,
        mapping_key,
        positional_arguments,
        positional_index,
    )
    cursor, precision_values, positional_index = _parse_percent_precision(
        template,
        cursor,
        mapping_key,
        positional_arguments,
        positional_index,
    )
    while cursor < len(template) and template[cursor] in "hlL":
        cursor += 1
    if cursor >= len(template) or template[cursor] not in "diouxXeEfFgGcrsa":
        raise ValueError("malformed percent log format")
    next_cursor = cursor + 1
    return _PercentFormatField(
        mapping_key=mapping_key,
        specification=f"%{template[format_body_start:next_cursor]}",
        dynamic_values=(*width_values, *precision_values),
        next_cursor=next_cursor,
        next_positional_index=positional_index,
    )


def _percent_field_value(
    field: _PercentFormatField,
    positional_arguments: tuple[object, ...] | None,
    mapping_arguments: Mapping[str, object] | None,
    positional_index: int,
    mapping_as_value_used: bool,
) -> tuple[object, int, bool]:
    if field.mapping_key is not None:
        if type(mapping_arguments) is not dict:
            raise TypeError("mapping field requires a plain mapping")
        return (
            dict.__getitem__(mapping_arguments, field.mapping_key),
            positional_index,
            mapping_as_value_used,
        )
    if positional_arguments is not None:
        if positional_index >= len(positional_arguments):
            raise TypeError("not enough log arguments")
        return positional_arguments[positional_index], positional_index + 1, False
    if mapping_as_value_used:
        raise TypeError("mapping log argument used more than once")
    return mapping_arguments, positional_index, True


def _bounded_percent_format(
    template: str,
    arguments: tuple[object, ...] | Mapping[str, object] | None,
) -> str:
    if not arguments:
        return template

    positional_arguments = arguments if type(arguments) is tuple else None
    mapping_arguments = (
        cast(Mapping[str, object], arguments)
        if type(arguments) is dict
        else None
    )
    if positional_arguments is None and mapping_arguments is None:
        raise TypeError("unsupported log arguments")

    pieces: list[str] = []
    output_length = 0
    positional_index = 0
    mapping_as_value_used = False
    literal_start = 0
    cursor = 0

    while cursor < len(template):
        if template[cursor] != "%":
            cursor += 1
            continue
        output_length = _append_bounded_log_text(
            pieces,
            template[literal_start:cursor],
            output_length,
        )
        if cursor + 1 < len(template) and template[cursor + 1] == "%":
            output_length = _append_bounded_log_text(
                pieces,
                "%",
                output_length,
            )
            cursor += 2
            literal_start = cursor
            continue
        field = _parse_percent_field(
            template,
            cursor,
            positional_arguments,
            positional_index,
        )
        positional_index = field.next_positional_index
        field_value, positional_index, mapping_as_value_used = _percent_field_value(
            field,
            positional_arguments,
            mapping_arguments,
            positional_index,
            mapping_as_value_used,
        )
        rendered_field = field.specification % (*field.dynamic_values, field_value)
        output_length = _append_bounded_log_text(
            pieces,
            rendered_field,
            output_length,
        )
        cursor = field.next_cursor
        literal_start = cursor

    output_length = _append_bounded_log_text(
        pieces,
        template[literal_start:],
        output_length,
    )
    del output_length
    if positional_arguments is not None and positional_index != len(
        positional_arguments
    ):
        raise TypeError("not all log arguments converted")
    return "".join(pieces)


def _bound_log_text(text: str) -> str:
    if len(text) <= _MAX_LOG_TEXT_CHARACTERS:
        return text
    return "log_text=[REDACTED]; log_text_truncated=present"


def _redact_non_json_text(text: str) -> str:
    text = _PRIVATE_KEY_BLOCK_PATTERN.sub(_REDACTED, text)
    text = _PUTTY_PRIVATE_KEY_PATTERN.sub(_REDACTED, text)
    text = _SSH2_PRIVATE_KEY_PATTERN.sub(_REDACTED, text)
    text = _AGE_PRIVATE_KEY_PATTERN.sub(_REDACTED, text)
    text = _redact_signing_private_key(text)
    text = _redact_private_data_uris(text)
    text = _redact_private_jwk(text)
    text = _AUTHORIZATION_PATTERN.sub(_redact_to_end, text)
    text = _BEARER_PATTERN.sub(rf"\1{_REDACTED}", text)
    text = _redact_credential_uris(text)
    text = _redact_sip_credentials(text)
    text = _CONNECTION_VALUE_PATTERN.sub(_redact_to_end, text)
    text = _COMPOUND_CREDENTIAL_VALUE_PATTERN.sub(_redact_to_end, text)
    text = _redact_sensitive_assignment(text)
    text = _WHITESPACE_CREDENTIAL_PATTERN.sub(_redact_to_end, text)
    return _SENSITIVE_CONTENT_PATTERN.sub(_redact_to_end, text)


def _inspect_json_string_value(
    item: str,
) -> tuple[bool, object | None]:
    if _redact_non_json_text(item) != item:
        return True, None
    decoded_item, inspection_truncated = _canonicalize_encoded_log_text(item)
    if inspection_truncated:
        return True, None
    if decoded_item != item and _redact_non_json_text(decoded_item) != decoded_item:
        return True, None
    nested_candidate = decoded_item.lstrip()
    if not nested_candidate.startswith(("{", "[", '"')):
        return False, None
    try:
        nested = json.loads(
            decoded_item,
            object_pairs_hook=_JsonObjectPairs,
        )
    except (TypeError, ValueError):
        return False, None
    except (MemoryError, RecursionError):
        return True, None
    return False, nested


def _append_json_object_members(
    item: _JsonObjectPairs,
    depth: int,
    pending: list[tuple[object, int]],
) -> bool:
    for key, member in item:
        if type(key) is str and _is_sensitive_label(key):
            return True
        pending.append((member, depth + 1))
    return False


def _json_inspection_budget_exhausted(
    remaining_items: int,
    depth: int,
) -> bool:
    return remaining_items <= 0 or depth > _MAX_EXCEPTION_CHAIN_DEPTH


def _append_json_container_members(
    item: object,
    depth: int,
    pending: list[tuple[object, int]],
) -> bool:
    if type(item) is _JsonObjectPairs:
        return _append_json_object_members(item, depth, pending)
    if type(item) is list:
        pending.extend(
            (member, depth + 1)
            for member in cast(list[object], item)
        )
    return False


def _json_contains_sensitive_string(text: str) -> bool:
    try:
        parsed = json.loads(text, object_pairs_hook=_JsonObjectPairs)
    except (TypeError, ValueError):
        return False
    except (MemoryError, RecursionError):
        return True

    pending: list[tuple[object, int]] = [(parsed, 0)]
    remaining_items = _MAX_ARGUMENT_TRAVERSAL_ITEMS
    remaining_characters = _MAX_LOG_TEXT_CHARACTERS
    while pending:
        item, depth = pending.pop()
        if _json_inspection_budget_exhausted(remaining_items, depth):
            return True
        remaining_items -= 1
        if type(item) is str:
            remaining_characters -= len(item)
            if remaining_characters < 0:
                return True
            sensitive, nested = _inspect_json_string_value(item)
            if sensitive:
                return True
            if nested is not None:
                pending.append((nested, depth + 1))
        elif _append_json_container_members(item, depth, pending):
            return True
    return False


def _redact_non_form_text(text: str) -> str:
    redacted = _redact_non_json_text(text)
    if redacted != text:
        return redacted
    if _json_contains_sensitive_string(text):
        return _REDACTED
    decoded_text, inspection_truncated = _canonicalize_encoded_log_text(text)
    if inspection_truncated:
        return _REDACTED
    if (
        decoded_text != text
        and _redact_non_json_text(decoded_text) != decoded_text
    ):
        return _REDACTED
    if decoded_text != text and _json_contains_sensitive_string(decoded_text):
        return _REDACTED
    return text


def redact_log_text(value: object) -> str:
    """Redact recognizable confidential values from one log-formatted value.

    This boundary intentionally makes no claim about unlabelled entropy. Central
    exception messages are handled separately and never enter managed output.
    """
    try:
        sanitized_value = value if type(value) is str else _sanitize_log_value(value)
        text = sanitized_value if type(sanitized_value) is str else str(sanitized_value)
        text = _bound_log_text(text)
    except BaseException:
        return "log_message=[REDACTED]; format_error=present"

    try:
        text = _redact_non_form_text(text)
        text = _redact_form_pairs(text)
        return _bound_log_text(text)
    except BaseException:
        return "log_message=[REDACTED]; redaction_error=present"


def _redact_isolated_diagnostic(value: object) -> str:
    redacted = redact_log_text(value)
    return _REDACTED if type(value) is str and redacted != value else redacted


def _safe_exception_type_name(exception_type: object) -> str:
    if not _is_actual_instance(exception_type, type):
        return "Exception"
    try:
        name = type.__getattribute__(exception_type, "__name__")
    except BaseException:
        return "Exception"
    if type(name) is str and _SAFE_EXCEPTION_TYPE_PATTERN.fullmatch(name):
        return name
    return "Exception"


def _read_exception_metadata(
    exception: BaseException,
    attribute: str,
) -> tuple[object, bool]:
    descriptor = BaseException.__dict__.get(attribute)
    if descriptor is None:
        return None, True
    try:
        return cast(Any, descriptor).__get__(exception, type(exception)), False
    except BaseException:
        return None, True


def _next_exception(
    exception: BaseException,
) -> tuple[BaseException | None, str]:
    cause, cause_unknown = _read_exception_metadata(exception, "__cause__")
    if cause_unknown:
        return None, "unknown"
    if _is_actual_instance(cause, BaseException):
        return cast(BaseException, cause), "cause"
    if cause is not None:
        return None, "unknown"

    suppress_context, suppress_context_unknown = _read_exception_metadata(
        exception,
        "__suppress_context__",
    )
    if suppress_context_unknown:
        return None, "unknown"
    if suppress_context is True:
        return None, "absent"
    if suppress_context is not False:
        return None, "unknown"

    context, context_unknown = _read_exception_metadata(exception, "__context__")
    if context_unknown:
        return None, "unknown"
    if _is_actual_instance(context, BaseException):
        return cast(BaseException, context), "context"
    if context is not None:
        return None, "unknown"
    return None, "absent"


def _exception_chain(
    exception: BaseException,
) -> tuple[list[BaseException], bool, int, int, bool]:
    chain: list[BaseException] = []
    seen: set[int] = set()
    current: BaseException | None = exception
    truncated = False
    cause_edges = 0
    context_edges = 0
    edge_unknown = False

    while current is not None and id(current) not in seen:
        if len(chain) >= _MAX_EXCEPTION_CHAIN_DEPTH:
            truncated = True
            break
        chain.append(current)
        seen.add(id(current))
        current, edge_kind = _next_exception(current)
        cause_edges += int(edge_kind == "cause")
        context_edges += int(edge_kind == "context")
        edge_unknown = edge_unknown or edge_kind == "unknown"

    if current is not None:
        truncated = True
    return chain, truncated, cause_edges, context_edges, edge_unknown


def _count_traceback_frames(traceback_value: TracebackType | None) -> tuple[int, bool]:
    count = 0
    seen: set[int] = set()
    current = traceback_value

    while current is not None and id(current) not in seen:
        if count >= _MAX_TRACEBACK_FRAMES:
            return count, True
        seen.add(id(current))
        count += 1
        current = current.tb_next
    return count, current is not None


def _safe_exception_traceback(
    exception: BaseException,
) -> tuple[TracebackType | None, bool]:
    traceback_value, unknown = _read_exception_metadata(exception, "__traceback__")
    if unknown:
        return None, True
    if traceback_value is None or type(traceback_value) is TracebackType:
        return traceback_value, False
    return None, True


def _exception_note_diagnostics(
    exception: BaseException,
) -> tuple[int, bool, bool]:
    values, values_unknown = _read_exception_metadata(exception, "__dict__")
    if values_unknown or type(values) is not dict:
        return 0, False, True
    notes: object | None = None
    note_key_found = False
    for key, candidate in islice(
        dict.items(values),
        _MAX_EXCEPTION_METADATA_ITEMS + 1,
    ):
        if type(key) is str and key == "__notes__":
            notes = candidate
            note_key_found = True
            break
    if not note_key_found:
        return (
            (0, False, True)
            if dict.__len__(values) > _MAX_EXCEPTION_METADATA_ITEMS
            else (0, False, False)
        )
    if type(notes) is not list:
        return 0, False, True
    note_count = list.__len__(notes)
    return min(note_count, _MAX_EXCEPTION_NOTES), note_count > _MAX_EXCEPTION_NOTES, False


def _bounded_exception_group_children(
    exception: BaseExceptionGroup,
    capacity: int,
) -> tuple[list[BaseException], bool]:
    try:
        descriptor = BaseExceptionGroup.__dict__["exceptions"]
        raw_children: object = cast(Any, descriptor).__get__(exception, type(exception))
    except BaseException:
        return [], True
    if type(raw_children) is not tuple:
        return [], True

    children = cast(tuple[object, ...], raw_children)
    selected = children[: max(0, capacity)]
    safe_children = [
        cast(BaseException, child)
        for child in selected
        if _is_actual_instance(child, BaseException)
    ]
    truncated = len(selected) < len(children) or len(safe_children) < len(selected)
    return safe_children, truncated


@dataclass
class _ExceptionGroupTraversalState:
    pending: list[tuple[BaseException, int, bool, bool, int]]
    seen: set[int]
    type_names: list[str]
    group_count: int = 0
    leaf_count: int = 0
    maximum_depth: int = 0
    tree_node_count: int = 0
    truncated: bool = False
    child_chain_nodes: int = 0
    group_traceback_count: int = 0
    group_traceback_truncated: bool = False
    group_traceback_unknown: bool = False
    group_note_count: int = 0
    group_notes_truncated: bool = False
    group_notes_unknown: bool = False
    group_cause_edges: int = 0
    group_context_edges: int = 0
    group_edge_unknown: bool = False
    causal_group_nodes: int = 0
    causal_group_count: int = 0
    causal_group_leaf_count: int = 0
    causal_group_depth: int = 0


def _accept_exception_group_node(
    state: _ExceptionGroupTraversalState,
    item: BaseException,
    depth: int,
    is_chain_node: bool,
    causal_depth: int,
) -> bool:
    if id(item) in state.seen:
        state.truncated = True
        return False
    if len(state.seen) >= _MAX_EXCEPTION_GROUP_NODES or depth > (
        _MAX_EXCEPTION_CHAIN_DEPTH
    ):
        state.truncated = True
        return False
    state.seen.add(id(item))
    if not is_chain_node and causal_depth == 0:
        state.tree_node_count += 1
        state.maximum_depth = max(state.maximum_depth, depth)
    elif causal_depth > 0:
        state.causal_group_nodes += 1
        state.causal_group_depth = max(state.causal_group_depth, causal_depth)
    state.type_names.append(_safe_exception_type_name(type(item)))
    state.child_chain_nodes += int(is_chain_node)
    return True


def _record_exception_group_diagnostics(
    state: _ExceptionGroupTraversalState,
    item: BaseException,
    depth: int,
) -> None:
    item_traceback, unknown = _safe_exception_traceback(item)
    state.group_traceback_unknown = state.group_traceback_unknown or unknown
    if state.group_traceback_count >= _MAX_TRACEBACK_FRAMES:
        state.group_traceback_truncated = (
            state.group_traceback_truncated or item_traceback is not None
        )
    else:
        count, traceback_truncated = _count_traceback_frames(item_traceback)
        remaining_frames = _MAX_TRACEBACK_FRAMES - state.group_traceback_count
        state.group_traceback_count += min(count, remaining_frames)
        state.group_traceback_truncated = (
            state.group_traceback_truncated
            or traceback_truncated
            or count > remaining_frames
        )

    next_exception, edge_kind = _next_exception(item)
    state.group_cause_edges += int(edge_kind == "cause")
    state.group_context_edges += int(edge_kind == "context")
    state.group_edge_unknown = state.group_edge_unknown or edge_kind == "unknown"
    if next_exception is not None:
        state.pending.append((next_exception, depth + 1, True, True, 0))

    note_count, notes_truncated, notes_unknown = _exception_note_diagnostics(item)
    remaining_notes = _MAX_EXCEPTION_NOTES - state.group_note_count
    state.group_note_count += min(note_count, remaining_notes)
    state.group_notes_truncated = (
        state.group_notes_truncated
        or notes_truncated
        or note_count > remaining_notes
    )
    state.group_notes_unknown = state.group_notes_unknown or notes_unknown


def _append_exception_group_children(
    state: _ExceptionGroupTraversalState,
    item: BaseException,
    depth: int,
    is_chain_node: bool,
    causal_depth: int,
) -> None:
    if not _is_actual_instance(item, BaseExceptionGroup):
        if not is_chain_node and causal_depth == 0:
            state.leaf_count += 1
        elif causal_depth > 0:
            state.causal_group_leaf_count += 1
        return
    if not is_chain_node and causal_depth == 0:
        state.group_count += 1
    elif is_chain_node:
        state.causal_group_nodes += 1
        state.causal_group_count += 1
        state.causal_group_depth = max(state.causal_group_depth, 1)
        causal_depth = 1
    else:
        state.causal_group_count += 1
    remaining_capacity = (
        _MAX_EXCEPTION_GROUP_NODES - len(state.seen) - len(state.pending)
    )
    children, children_truncated = _bounded_exception_group_children(
        cast(BaseExceptionGroup, item),
        remaining_capacity,
    )
    state.truncated = state.truncated or children_truncated
    state.pending.extend(
        (
            child,
            depth + 1,
            True,
            False,
            causal_depth + 1 if causal_depth else 0,
        )
        for child in reversed(children)
    )


def _exception_group_summary(
    exceptions: list[BaseException],
) -> _ExceptionGroupSummary:
    group_roots = [
        item
        for item in exceptions
        if _is_actual_instance(item, BaseExceptionGroup)
    ]
    if not group_roots:
        return _ExceptionGroupSummary("")

    state = _ExceptionGroupTraversalState(
        pending=[
            (item, 1, False, False, 0) for item in reversed(group_roots)
        ],
        seen=set(),
        type_names=[],
    )
    while state.pending:
        (
            item,
            depth,
            include_diagnostics,
            is_chain_node,
            causal_depth,
        ) = state.pending.pop()
        if not _accept_exception_group_node(
            state,
            item,
            depth,
            is_chain_node,
            causal_depth,
        ):
            continue
        if include_diagnostics:
            _record_exception_group_diagnostics(state, item, depth)
        _append_exception_group_children(
            state,
            item,
            depth,
            is_chain_node,
            causal_depth,
        )

    type_names = state.type_names
    group_count = state.group_count
    leaf_count = state.leaf_count
    maximum_depth = state.maximum_depth
    tree_node_count = state.tree_node_count
    truncated = state.truncated
    child_chain_nodes = state.child_chain_nodes
    group_traceback_count = state.group_traceback_count
    group_traceback_truncated = state.group_traceback_truncated
    group_traceback_unknown = state.group_traceback_unknown
    group_note_count = state.group_note_count
    group_notes_truncated = state.group_notes_truncated
    group_notes_unknown = state.group_notes_unknown
    group_cause_edges = state.group_cause_edges
    group_context_edges = state.group_context_edges
    group_edge_unknown = state.group_edge_unknown
    causal_group_nodes = state.causal_group_nodes
    causal_group_count = state.causal_group_count
    causal_group_leaf_count = state.causal_group_leaf_count
    causal_group_depth = state.causal_group_depth
    rendered_types = " -> ".join(type_names) if type_names else "ExceptionGroup"
    traceback_status = (
        "present"
        if group_traceback_count > 0
        else "unknown"
        if group_traceback_unknown
        else "absent"
    )
    group_notes_status = (
        "present"
        if group_note_count
        else "unknown"
        if group_notes_unknown
        else "absent"
    )
    summary = (
        "; group=present; "
        f"group_roots={len(group_roots)}; "
        f"group_nodes={tree_node_count}; "
        f"group_count={group_count}; "
        f"group_leaf_count={leaf_count}; "
        f"group_depth={maximum_depth}; "
        f"group_truncated={'yes' if truncated else 'no'}; "
        f"group_child_chain={'present' if child_chain_nodes else 'absent'}; "
        f"group_child_chain_nodes={child_chain_nodes}; "
        f"group_cause_edges={group_cause_edges}; "
        f"group_context_edges={group_context_edges}; "
        f"group_chain_edge_unknown={'yes' if group_edge_unknown else 'no'}; "
        f"group_causal_group_nodes={causal_group_nodes}; "
        f"group_causal_group_count={causal_group_count}; "
        f"group_causal_group_leaf_count={causal_group_leaf_count}; "
        f"group_causal_group_depth={causal_group_depth}; "
        f"group_traceback={traceback_status}; "
        f"group_traceback_frames={group_traceback_count}; "
        f"group_traceback_truncated={'yes' if group_traceback_truncated else 'no'}; "
        f"group_traceback_unknown={'yes' if group_traceback_unknown else 'no'}; "
        f"group_notes={group_notes_status}; "
        f"group_note_count={group_note_count}; "
        f"group_notes_truncated={'yes' if group_notes_truncated else 'no'}; "
        f"group_notes_unknown={'yes' if group_notes_unknown else 'no'}; "
        f"group_exception_types={rendered_types}"
    )
    return _ExceptionGroupSummary(
        text=summary,
        traceback_count=group_traceback_count,
        traceback_truncated=group_traceback_truncated,
        traceback_unknown=group_traceback_unknown,
        note_count=group_note_count,
        notes_truncated=group_notes_truncated,
        notes_unknown=group_notes_unknown,
        cause_edges=group_cause_edges,
        context_edges=group_context_edges,
        edge_unknown=group_edge_unknown,
    )


def summarize_exception(
    exception: BaseException,
    *,
    traceback_override: TracebackType | None | _TracebackNotProvided = _TRACEBACK_NOT_PROVIDED,
) -> str:
    """Return message-free exception structure suitable for managed logs."""
    (
        chain,
        chain_truncated,
        cause_edges,
        context_edges,
        chain_edge_unknown,
    ) = _exception_chain(exception)
    names = [_safe_exception_type_name(type(item)) for item in chain]
    if not names:
        names = ["Exception"]

    traceback_count = 0
    traceback_truncated = False
    traceback_unknown = False
    note_count = 0
    notes_truncated = False
    notes_unknown = False
    for index, item in enumerate(chain):
        if index == 0 and type(traceback_override) is not _TracebackNotProvided:
            raw_traceback_override: object = traceback_override
            if raw_traceback_override is None or (
                type(raw_traceback_override) is TracebackType
            ):
                item_traceback = raw_traceback_override
            else:
                item_traceback = None
                traceback_unknown = True
        else:
            item_traceback, unknown = _safe_exception_traceback(item)
            traceback_unknown = traceback_unknown or unknown
        if traceback_count >= _MAX_TRACEBACK_FRAMES:
            traceback_truncated = traceback_truncated or item_traceback is not None
        else:
            count, truncated = _count_traceback_frames(item_traceback)
            remaining_frames = _MAX_TRACEBACK_FRAMES - traceback_count
            traceback_count += min(count, remaining_frames)
            traceback_truncated = (
                traceback_truncated or truncated or count > remaining_frames
            )

        item_note_count, item_notes_truncated, item_notes_unknown = (
            _exception_note_diagnostics(item)
        )
        remaining_notes = _MAX_EXCEPTION_NOTES - note_count
        note_count += min(item_note_count, remaining_notes)
        notes_truncated = (
            notes_truncated
            or item_notes_truncated
            or item_note_count > remaining_notes
        )
        notes_unknown = notes_unknown or item_notes_unknown

    group_summary = _exception_group_summary(chain)
    remaining_frames = _MAX_TRACEBACK_FRAMES - traceback_count
    traceback_count += min(group_summary.traceback_count, remaining_frames)
    traceback_truncated = (
        traceback_truncated
        or group_summary.traceback_truncated
        or group_summary.traceback_count > remaining_frames
    )
    traceback_unknown = traceback_unknown or group_summary.traceback_unknown
    remaining_notes = _MAX_EXCEPTION_NOTES - note_count
    note_count += min(group_summary.note_count, remaining_notes)
    notes_truncated = (
        notes_truncated
        or group_summary.notes_truncated
        or group_summary.note_count > remaining_notes
    )
    notes_unknown = notes_unknown or group_summary.notes_unknown
    cause_edges += group_summary.cause_edges
    context_edges += group_summary.context_edges
    chain_edge_unknown = chain_edge_unknown or group_summary.edge_unknown

    chain_present = len(chain) > 1 or chain_truncated
    if traceback_count > 0:
        traceback_status = "present"
    elif traceback_unknown:
        traceback_status = "unknown"
    else:
        traceback_status = "absent"
    chain_order = " -> ".join(reversed(names))
    return (
        f"exception_type={names[0]}; "
        f"traceback={traceback_status}; "
        f"traceback_frames={traceback_count}; "
        f"traceback_truncated={'yes' if traceback_truncated else 'no'}; "
        f"traceback_unknown={'yes' if traceback_unknown else 'no'}; "
        f"chain={'present' if chain_present else 'absent'}; "
        f"chain_truncated={'yes' if chain_truncated else 'no'}; "
        f"cause_edges={cause_edges}; "
        f"context_edges={context_edges}; "
        f"chain_edge_unknown={'yes' if chain_edge_unknown else 'no'}; "
        f"notes={'present' if note_count else 'unknown' if notes_unknown else 'absent'}; "
        f"note_count={note_count}; "
        f"notes_truncated={'yes' if notes_truncated else 'no'}; "
        f"notes_unknown={'yes' if notes_unknown else 'no'}; "
        f"exception_chain={chain_order}"
        f"{group_summary.text}"
    )


def _fallback_exception_summary(exc_info: Any) -> str:
    if type(exc_info) is not tuple or len(exc_info) != 3:
        return "exception_type=Exception; traceback=unknown; chain=unknown"
    exception_type, exception, traceback_value = exc_info

    if _is_actual_instance(exception, BaseException):
        return summarize_exception(
            exception,
            traceback_override=cast(Any, traceback_value),
        )

    name = _safe_exception_type_name(exception_type)
    traceback_present = type(traceback_value) is TracebackType
    return (
        f"exception_type={name}; "
        f"traceback={'present' if traceback_present else 'absent'}; "
        "chain=unknown"
    )


def _safe_stack_summary(stack_info: object) -> str:
    if type(stack_info) is not str:
        return "stack=unknown; stack_lines=unknown"
    if len(stack_info) > _MAX_LOG_TEXT_CHARACTERS:
        return "stack=present; stack_lines=unknown; stack_truncated=yes"

    line_count = 0
    cursor = 0
    line_breaks = "\n\v\f\x1c\x1d\x1e\x85\u2028\u2029"
    while cursor < len(stack_info):
        character = stack_info[cursor]
        if character == "\r":
            line_count += 1
            if cursor + 1 < len(stack_info) and stack_info[cursor + 1] == "\n":
                cursor += 1
        elif character in line_breaks:
            line_count += 1
        cursor += 1
    if stack_info and stack_info[-1] not in f"\r{line_breaks}":
        line_count += 1
    return f"stack=present; stack_lines={line_count}; stack_truncated=no"


def _fallback_log_record() -> logging.LogRecord:
    return logging.LogRecord(
        "logging",
        logging.ERROR,
        "",
        0,
        "log_message=[REDACTED]; format_error=present",
        (),
        None,
    )


def _base_log_record_copy(
    record: object,
) -> tuple[logging.LogRecord, dict[object, object]] | None:
    if not _is_actual_instance(record, logging.LogRecord):
        return None
    try:
        record_dict_descriptor = logging.LogRecord.__dict__["__dict__"]
        raw_values = cast(
            object,
            record_dict_descriptor.__get__(record, type(record)),
        )
        if type(raw_values) is not dict:
            return None
        safe_record = _fallback_log_record()
        safe_values = object.__getattribute__(safe_record, "__dict__")
        selected_values: dict[object, object] = {}
        copied_extras = 0
        scan_limit = len(_LOG_RECORD_CORE_FIELDS) + _MAX_LOG_RECORD_EXTRAS + 1
        for key, value in islice(dict.items(raw_values), scan_limit):
            if type(key) is not str:
                continue
            selected_values[key] = value
            if key in _LOG_RECORD_CORE_FIELDS:
                safe_values[key] = value
                continue
            if copied_extras >= _MAX_LOG_RECORD_EXTRAS:
                safe_values["record_extras_truncated"] = True
                break
            safe_values[key] = value
            copied_extras += 1
        if dict.__len__(raw_values) > scan_limit:
            safe_values["record_extras_truncated"] = True
    except BaseException:
        return None
    return safe_record, selected_values


def _sanitize_record_extras(
    record: logging.LogRecord,
    state: _ArgumentSanitizationState,
) -> None:
    record_values = object.__getattribute__(record, "__dict__")
    protected = {
        "args",
        "exc_info",
        "exc_text",
        "message",
        "msg",
        "name",
        "stack_info",
        "threadName",
        "levelname",
    }
    for key, value in list(record_values.items()):
        if type(key) is not str:
            del record_values[key]
        elif key == "getMessage":
            del record_values[key]
        elif key in protected:
            continue
        elif key in _SENSITIVE_LOG_RECORD_CORE_FIELDS:
            record_values[key] = _REDACTED
        elif key in _LOG_RECORD_CORE_FIELDS:
            sanitized = _sanitize_log_value(value, state=state)
            record_values[key] = (
                redact_log_text(sanitized) if type(sanitized) is str else sanitized
            )
        elif _is_sensitive_label(key):
            del record_values[key]
        else:
            sanitized = _sanitize_log_value(value, state=state)
            record_values[key] = (
                redact_log_text(sanitized) if type(sanitized) is str else sanitized
            )


def _redact_template_text_values(value: object) -> object:
    if type(value) in (str, bytes):
        return _REDACTED
    if type(value) is dict:
        mapping_value = cast(dict[object, object], value)
        return {
            key: _redact_template_text_values(item)
            for key, item in mapping_value.items()
        }
    if type(value) is list:
        return [_redact_template_text_values(item) for item in cast(list[object], value)]
    if type(value) is tuple:
        return tuple(
            _redact_template_text_values(item)
            for item in cast(tuple[object, ...], value)
        )
    return value


def _sanitized_record_copy(
    record: object,
    *,
    state: _ArgumentSanitizationState | None = None,
) -> logging.LogRecord:
    copied_record = _base_log_record_copy(record)
    if copied_record is None:
        return _fallback_log_record()
    safe_record, raw_values = copied_record
    active_state = _ArgumentSanitizationState(set()) if state is None else state
    try:
        safe_record.msg, template_usable = _sanitize_message_template(
            raw_values.get("msg"),
            active_state,
        )
        raw_arguments = cast(
            tuple[object, ...] | Mapping[str, object] | None,
            raw_values.get("args"),
        )
        safe_record.args = (
            _redact_record_arguments(raw_arguments, state=active_state)
            if template_usable
            else ()
        )
        resolved_message = _bounded_percent_format(
            str(safe_record.msg),
            safe_record.args,
        )
    except BaseException:
        resolved_message = "log_message=[REDACTED]; format_error=present"

    diagnostics: list[str] = []
    carried_exception_summary = raw_values.get("_metroliza_exception_summary")
    carried_stack_summary = raw_values.get("_metroliza_stack_summary")
    if type(carried_exception_summary) is str:
        diagnostics.append(carried_exception_summary)
    if type(carried_stack_summary) is str:
        diagnostics.append(carried_stack_summary)
    raw_exc_info = raw_values.get("exc_info")
    raw_exc_text = raw_values.get("exc_text")
    raw_stack_info = raw_values.get("stack_info")
    if raw_exc_info is not None:
        diagnostics.append(_fallback_exception_summary(raw_exc_info))
    elif raw_exc_text is not None:
        diagnostics.append("exception_text=present; exception_details=[REDACTED]")
    if raw_stack_info is not None:
        diagnostics.append(_safe_stack_summary(raw_stack_info))

    safe_message = redact_log_text(resolved_message)
    safe_record.msg = "; ".join(
        [*(_redact_isolated_diagnostic(item) for item in diagnostics), safe_message]
    )
    safe_record.args = ()
    safe_record.message = safe_record.msg
    safe_record.exc_info = None
    safe_record.exc_text = None
    safe_record.stack_info = None
    safe_record.name = _redact_isolated_diagnostic(raw_values.get("name"))
    safe_record.threadName = _redact_isolated_diagnostic(raw_values.get("threadName"))
    safe_record.levelname = _redact_isolated_diagnostic(raw_values.get("levelname"))
    _sanitize_record_extras(safe_record, active_state)
    return safe_record


def _sanitized_template_record_copy(record: object) -> logging.LogRecord:
    copied_record = _base_log_record_copy(record)
    if copied_record is None:
        return _fallback_log_record()
    safe_record, raw_values = copied_record
    state = _ArgumentSanitizationState(set())

    safe_template_value, template_usable = _sanitize_message_template(
        raw_values.get("msg"),
        state,
    )
    safe_template = redact_log_text(safe_template_value)
    raw_arguments = cast(
        tuple[object, ...] | Mapping[str, object] | None,
        raw_values.get("args"),
    )
    safe_arguments = _redact_template_text_values(
        _redact_record_arguments(raw_arguments, state=state)
    )
    if not template_usable or safe_template_value != safe_template:
        safe_arguments = ()

    safe_record.msg = safe_template
    safe_record.args = cast(
        tuple[object, ...] | Mapping[str, object] | None,
        safe_arguments,
    )
    try:
        safe_record.message = _bounded_percent_format(
            str(safe_record.msg),
            safe_record.args,
        )
    except BaseException:
        safe_record.msg = "log_message=[REDACTED]; format_error=present"
        safe_record.args = ()
        safe_record.message = safe_record.msg

    raw_exc_info = raw_values.get("exc_info")
    if raw_exc_info is not None:
        safe_record._metroliza_exception_summary = _fallback_exception_summary(
            raw_exc_info
        )
    elif raw_values.get("exc_text") is not None:
        safe_record._metroliza_exception_summary = (
            "exception_text=present; exception_details=[REDACTED]"
        )
    raw_stack_info = raw_values.get("stack_info")
    if raw_stack_info is not None:
        safe_record._metroliza_stack_summary = _safe_stack_summary(raw_stack_info)

    safe_record.exc_info = None
    safe_record.exc_text = None
    safe_record.stack_info = None
    safe_record.name = _redact_isolated_diagnostic(raw_values.get("name"))
    safe_record.threadName = _redact_isolated_diagnostic(raw_values.get("threadName"))
    safe_record.levelname = _redact_isolated_diagnostic(raw_values.get("levelname"))
    _sanitize_record_extras(safe_record, state)
    return safe_record


class _RedactingFormatter(logging.Formatter):
    """Format a cloned record so managed handlers never mutate shared records."""

    def format(self, record: logging.LogRecord) -> str:
        safe_record = _sanitized_record_copy(record)

        try:
            rendered = super().format(safe_record)
        except BaseException:
            return "ERROR [logging] [unknown] log_message=[REDACTED]; format_error=present"
        return rendered

    def formatException(self, ei: Any) -> str:  # noqa: N802 - stdlib API
        try:
            return _fallback_exception_summary(ei)
        except BaseException:
            return "exception_type=Exception; traceback=unknown; chain=unknown"

    def formatStack(self, stack_info: str) -> str:  # noqa: N802 - stdlib API
        return _safe_stack_summary(stack_info)


def _handle_error_without_record_dump(record: logging.LogRecord) -> None:
    del record
    try:
        sys.stderr.write("Metroliza logging failure; record suppressed.\n")
    except BaseException:
        pass


class _SafeHandlerErrorMixin:
    """Prevent stdlib ``handleError`` from dumping a raw LogRecord."""

    def handleError(self, record: logging.LogRecord) -> None:  # noqa: N802 - stdlib API
        _handle_error_without_record_dump(record)


class _SafeRotatingFileHandler(
    _SafeHandlerErrorMixin,
    logging.handlers.RotatingFileHandler,
):
    pass


class _SafeStreamHandler(_SafeHandlerErrorMixin, logging.StreamHandler[Any]):
    pass


class _HandlerTransitionState:
    def __init__(self) -> None:
        self.active = False
        self.pending: list[logging.Handler] = []
        self.removed: list[logging.Handler] = []


class _HandlerBoundaryList(list[logging.Handler]):
    """Secure handlers registered after application logging is configured."""

    def __init__(
        self,
        handlers: list[logging.Handler],
        formatter: logging.Formatter,
    ) -> None:
        super().__init__(handlers)
        self.formatter = formatter
        self._transition = _HandlerTransitionState()

    @staticmethod
    def _contains_identity(
        handlers: Iterable[logging.Handler],
        candidate: object,
    ) -> bool:
        return any(handler is candidate for handler in handlers)

    def __contains__(self, candidate: object) -> bool:
        return self._contains_identity(list.__iter__(self), candidate) or (
            self._transition.active
            and self._contains_identity(self._transition.pending, candidate)
            and not self._contains_identity(self._transition.removed, candidate)
        )

    def copy(self) -> Self:
        visible_handlers = list(list.__iter__(self))
        if self._transition.active:
            for handler in self._transition.pending:
                if (
                    not self._contains_identity(self._transition.removed, handler)
                    and not self._contains_identity(visible_handlers, handler)
                ):
                    visible_handlers.append(handler)
        copied = _HandlerBoundaryList(
            visible_handlers,
            self.formatter,
        )
        return cast(Self, copied)

    def begin_transition(
        self,
        handlers: Iterable[logging.Handler] | None = None,
    ) -> list[logging.Handler]:
        pending = (
            list(list.__iter__(self))
            if handlers is None
            else list(handlers)
        )
        list.clear(self)
        self._transition.active = True
        self._transition.pending = pending
        self._transition.removed = []
        return list(pending)

    def pending(self, handler: logging.Handler) -> bool:
        return self._transition.active and self._contains_identity(
            self._transition.pending,
            handler,
        ) and not (
            self._contains_identity(self._transition.removed, handler)
        )

    def complete_transition_handler(self, handler: logging.Handler) -> None:
        if self.pending(handler):
            list.append(self, handler)
        self._transition.pending = [
            pending
            for pending in self._transition.pending
            if pending is not handler
        ]

    def finish_transition(self) -> None:
        self._transition.active = False
        self._transition.pending = []
        self._transition.removed = []

    def remove(self, handler: logging.Handler) -> None:
        for index, existing in enumerate(list.__iter__(self)):
            if existing is handler:
                list.__delitem__(self, index)
                return
        if self.pending(handler):
            self._transition.removed.append(handler)
            return
        raise ValueError("list.remove(x): x not in list")

    def clear(self) -> None:
        self._transition.removed.extend(
            handler
            for handler in self._transition.pending
            if not self._contains_identity(self._transition.removed, handler)
        )
        list.clear(self)

    def append(self, handler: logging.Handler) -> None:
        _harden_handler(handler, self.formatter, replace_formatter=False)
        super().append(handler)

    def insert(self, index: SupportsIndex, handler: logging.Handler) -> None:
        _harden_handler(handler, self.formatter, replace_formatter=False)
        super().insert(index, handler)

    def extend(self, handlers: Iterable[logging.Handler]) -> None:
        for handler in list(handlers):
            self.append(handler)

    # Mypy compares this in-place signature with overloaded ``list.__add__``
    # as well as the compatible ``MutableSequence.__iadd__`` contract.
    def __iadd__(  # type: ignore[override,misc]
        self,
        handlers: Iterable[logging.Handler],
    ) -> Self:
        self.extend(handlers)
        return self

    @overload
    def __setitem__(self, index: SupportsIndex, handler: logging.Handler) -> None: ...

    @overload
    def __setitem__(
        self,
        index: slice,
        handler: Iterable[logging.Handler],
    ) -> None: ...

    def __setitem__(
        self,
        index: SupportsIndex | slice,
        handler: logging.Handler | Iterable[logging.Handler],
    ) -> None:
        if type(index) is slice:
            handlers = list(cast(Iterable[logging.Handler], handler))
            for item in handlers:
                _harden_handler(item, self.formatter, replace_formatter=False)
            super().__setitem__(index, handlers)
            return
        single_handler = cast(logging.Handler, handler)
        _harden_handler(single_handler, self.formatter, replace_formatter=False)
        super().__setitem__(index, single_handler)


def _is_trusted_output_handler(handler: logging.Handler) -> bool:
    return type(handler) in {
        logging.StreamHandler,
        logging.FileHandler,
        logging.handlers.RotatingFileHandler,
        _SafeStreamHandler,
        _SafeRotatingFileHandler,
    }


def _sanitize_buffered_records(handler: logging.Handler) -> None:
    if not _is_actual_instance(handler, logging.handlers.BufferingHandler):
        return
    handler_values = _handler_values(handler)
    if handler_values is None:
        return
    raw_buffer = handler_values.get("buffer")
    if not (
        _is_actual_instance(raw_buffer, list)
        or _is_actual_instance(raw_buffer, deque)
    ):
        handler_values["buffer"] = [_fallback_log_record()]
        return
    if _is_actual_instance(raw_buffer, list):
        list_buffer = cast(list[object], raw_buffer)
        buffer_length = list.__len__(list_buffer)
        buffered_records = list(
            islice(list.__iter__(list_buffer), _MAX_BUFFERED_LOG_RECORDS)
        )
    else:
        deque_buffer = cast(deque[object], raw_buffer)
        buffer_length = deque.__len__(deque_buffer)
        buffered_records = list(
            islice(deque.__iter__(deque_buffer), _MAX_BUFFERED_LOG_RECORDS)
        )
    sanitized_records: list[logging.LogRecord] = []
    buffer_state = _ArgumentSanitizationState(set())
    buffer_truncated = buffer_length > _MAX_BUFFERED_LOG_RECORDS
    for record in buffered_records:
        if (
            buffer_state.remaining_items <= 0
            or buffer_state.remaining_characters <= 0
        ):
            buffer_truncated = True
            break
        sanitized_records.append(
            _sanitized_record_copy(record, state=buffer_state)
            if _is_actual_instance(record, logging.LogRecord)
            else _fallback_log_record()
        )
    if buffer_truncated:
        truncation_record = _fallback_log_record()
        truncation_record.msg = (
            "log_buffer=[REDACTED]; buffered_records_truncated=present"
        )
        truncation_record.args = ()
        sanitized_records.append(truncation_record)
    if _is_actual_instance(raw_buffer, deque):
        deque_buffer = cast(deque[object], raw_buffer)
        deque.clear(deque_buffer)
        deque.extend(deque_buffer, sanitized_records)
    else:
        list_buffer = cast(list[object], raw_buffer)
        list.__setitem__(list_buffer, slice(None), sanitized_records)


def _harden_handler(
    handler: logging.Handler,
    formatter: logging.Formatter,
    *,
    replace_formatter: bool = True,
    _seen: set[int] | None = None,
) -> None:
    active_seen = set() if _seen is None else _seen
    if id(handler) in active_seen:
        return
    active_seen.add(id(handler))

    logging.Handler.acquire(handler)
    try:
        if replace_formatter:
            logging.Handler.setFormatter(handler, formatter)
            object.__setattr__(handler, "handleError", _handle_error_without_record_dump)
        _sanitize_buffered_records(handler)
        _install_record_boundary(handler)
        _install_memory_target_boundary(handler, formatter)
        target = _memory_handler_target(handler)
        if target is not None:
            _harden_handler(
                target,
                formatter,
                replace_formatter=False,
                _seen=active_seen,
            )
    finally:
        logging.Handler.release(handler)


def _memory_handler_target(handler: logging.Handler) -> logging.Handler | None:
    if not _is_actual_instance(handler, logging.handlers.MemoryHandler):
        return None
    handler_values = _handler_values(handler)
    if handler_values is None:
        return None
    target = handler_values.get("target")
    return target if _is_actual_instance(target, logging.Handler) else None


def _install_memory_target_boundary(
    handler: logging.Handler,
    formatter: logging.Formatter,
) -> None:
    if not _is_actual_instance(handler, logging.handlers.MemoryHandler):
        return
    handler_values = _handler_values(handler)
    if handler_values is None:
        return
    original_set_target = handler_values.get("_metroliza_original_set_target")
    if not callable(original_set_target):
        memory_handler = cast(logging.handlers.MemoryHandler, handler)
        original_set_target = memory_handler.setTarget
        object.__setattr__(
            handler,
            "_metroliza_original_set_target",
            original_set_target,
        )

    def set_target_safely(target: logging.Handler | None) -> Any:
        if _is_actual_instance(target, logging.Handler):
            _harden_handler(
                cast(logging.Handler, target),
                formatter,
                replace_formatter=False,
            )
        return original_set_target(target)

    object.__setattr__(handler, "setTarget", set_target_safely)


def _install_format_boundary(
    handler: logging.Handler,
    handler_values: dict[str, Any],
) -> None:
    original_format = handler_values.get("_metroliza_original_format")
    if not callable(original_format):
        original_format = handler.format
        object.__setattr__(handler, "_metroliza_original_format", original_format)

    def format_safely(record: logging.LogRecord) -> str:
        safe_record = _sanitized_record_copy(record)
        try:
            rendered = original_format(safe_record)
        except BaseException:
            return "log_message=[REDACTED]; format_error=present"
        return redact_log_text(rendered)

    object.__setattr__(handler, "format", format_safely)


def _install_emit_boundary(
    handler: logging.Handler,
    handler_values: dict[str, Any],
) -> None:
    original_emit = handler_values.get("_metroliza_original_emit")
    if not callable(original_emit):
        original_emit = handler.emit
        object.__setattr__(handler, "_metroliza_original_emit", original_emit)

    def emit_safely(record: logging.LogRecord) -> Any:
        safe_record = _sanitized_record_copy(record)
        try:
            return original_emit(safe_record)
        except Exception:
            _handle_error_without_record_dump(safe_record)
            return None

    object.__setattr__(handler, "emit", emit_safely)


def _install_handle_error_boundary(
    handler: logging.Handler,
    handler_values: dict[str, Any],
) -> None:
    original_handle_error = handler_values.get("_metroliza_original_handle_error")
    if not callable(original_handle_error):
        uses_standard_handle_error = (
            _type_member_without_metaclass_hooks(handler, "handleError")
            is logging.Handler.handleError
            and "handleError" not in handler_values
        )
        if uses_standard_handle_error:
            original_handle_error = _handle_error_without_record_dump
        else:
            original_handle_error = handler.handleError
        object.__setattr__(
            handler,
            "_metroliza_original_handle_error",
            original_handle_error,
        )

    def handle_error_safely(record: logging.LogRecord) -> Any:
        return original_handle_error(_sanitized_record_copy(record))

    object.__setattr__(handler, "handleError", handle_error_safely)


def _install_custom_handle_boundary(
    handler: logging.Handler,
    handler_values: dict[str, Any],
) -> None:
    uses_standard_handle = (
        _type_member_without_metaclass_hooks(handler, "handle")
        is logging.Handler.handle
        and "handle" not in handler_values
    )
    if not uses_standard_handle:
        original_handle = handler_values.get("_metroliza_original_handle")
        if not callable(original_handle):
            original_handle = handler.handle
            object.__setattr__(handler, "_metroliza_original_handle", original_handle)

        def handle_safely(record: logging.LogRecord) -> Any:
            return original_handle(_sanitized_template_record_copy(record))

        object.__setattr__(handler, "handle", handle_safely)


def _install_record_boundary(handler: logging.Handler) -> None:
    handler_values = _handler_values(handler)
    if handler_values is None:
        return
    _install_format_boundary(handler, handler_values)
    _install_emit_boundary(handler, handler_values)
    _install_handle_error_boundary(handler, handler_values)
    _install_custom_handle_boundary(handler, handler_values)


def _detach_existing_handlers(
    logger: logging.Logger,
    formatter: logging.Formatter,
) -> list[logging.Handler]:
    with _LOGGING_MODULE_LOCK:
        existing_handlers = logger.handlers
        if type(existing_handlers) is _HandlerBoundaryList:
            boundary = existing_handlers
            boundary.formatter = formatter
            return boundary.begin_transition()
        boundary = _HandlerBoundaryList([], formatter)
        object.__setattr__(
            logger,
            "handlers",
            boundary,
        )
        return boundary.begin_transition(existing_handlers)


def _reattach_hardened_handler(
    logger: logging.Logger,
    handler: logging.Handler,
    boundary: _HandlerBoundaryList,
) -> None:
    with _LOGGING_MODULE_LOCK:
        handlers = logger.handlers
        if handlers is boundary:
            boundary.complete_transition_handler(handler)


def _secure_existing_handlers(
    logger: logging.Logger,
    formatter: logging.Formatter,
    handlers: list[logging.Handler],
) -> None:
    boundary = (
        logger.handlers
        if type(logger.handlers) is _HandlerBoundaryList
        else None
    )
    try:
        for handler in handlers:
            with _LOGGING_MODULE_LOCK:
                current_handlers = logger.handlers
                retained = (
                    boundary.pending(handler)
                    if boundary is not None and current_handlers is boundary
                    else any(
                        existing is handler
                        for existing in current_handlers
                    )
                )
            if not retained:
                continue
            _harden_handler(handler, formatter, replace_formatter=False)
            if boundary is not None:
                _reattach_hardened_handler(logger, handler, boundary)
    finally:
        if boundary is not None:
            boundary.finish_transition()


def _secure_last_resort(formatter: logging.Formatter) -> None:
    with _LOGGING_MODULE_LOCK:
        handler = logging.lastResort
        if _is_actual_instance(handler, logging.Handler):
            try:
                _harden_handler(cast(logging.Handler, handler), formatter)
                return
            except BaseException:
                pass

        safe_handler = _SafeStreamHandler()
        logging.Handler.setLevel(safe_handler, logging.WARNING)
        _harden_handler(safe_handler, formatter)
        logging.lastResort = safe_handler


def _is_truthy(raw_value: str | None) -> bool:
    return cast(bool, parse_bool(raw_value, default=False))


def _parse_level(raw_value: str | None, *, fallback: int) -> int:
    if raw_value is None or str(raw_value).strip() == "":
        return fallback

    normalized = str(raw_value).strip().upper()
    if normalized.isdigit() or (normalized.startswith("-") and normalized[1:].isdigit()):
        return int(normalized)

    level_value = logging.getLevelName(normalized)
    if type(level_value) is int:
        return level_value
    return fallback


def _parse_optional_level(raw_value: str | None) -> int | None:
    """Parse a potentially disabled log level for optional console logging.

    Args:
        raw_value: Raw environment value.

    Returns:
        An integer logging level, or ``None`` when logging should be disabled.

    Notes:
        Values ``off``, ``none``, ``disable``, ``disabled``, and ``null`` are
        treated as explicit disablement signals.
    """

    if raw_value is None:
        return None

    stripped = str(raw_value).strip()
    if stripped == "":
        return None

    if stripped.lower() in {"off", "none", "disable", "disabled", "null"}:
        return None

    return _parse_level(stripped, fallback=logging.INFO)


def resolve_logging_config() -> LoggingConfig:
    """Resolve effective logging configuration from environment variables.

    Returns:
        A :class:`LoggingConfig` with resolved global, file, and console levels.

    Notes:
        Precedence is:

        1. ``METROLIZA_LOG_LEVEL`` for the root logger level.
        2. ``METROLIZA_FILE_LOG_LEVEL`` for file handlers, falling back to the
           resolved global level.
        3. ``METROLIZA_CONSOLE_LOG_LEVEL`` for console handlers, where
           ``off/none/disable/disabled/null`` disables console output.

        When ``METROLIZA_LOG_LEVEL`` is unset, support builds
        (``METROLIZA_SUPPORT_BUILD`` truthy) default to ``DEBUG`` and other
        builds default to ``INFO``.
    """

    default_global = logging.DEBUG if _is_truthy(os.getenv(_SUPPORT_BUILD_ENV)) else logging.INFO
    global_level = _parse_level(os.getenv(_GLOBAL_LEVEL_ENV), fallback=default_global)
    file_level = _parse_level(os.getenv(_FILE_LEVEL_ENV), fallback=global_level)
    console_level = _parse_optional_level(os.getenv(_CONSOLE_LEVEL_ENV))
    return LoggingConfig(global_level=global_level, file_level=file_level, console_level=console_level)


def _remove_handler(
    logger: logging.Logger,
    handler: logging.Handler,
    formatter: logging.Formatter,
) -> None:
    safe_emit: Callable[[logging.LogRecord], None] | None = None
    logging.Handler.acquire(handler)
    try:
        logging.Handler.setFormatter(handler, formatter)
        object.__setattr__(handler, "handleError", _handle_error_without_record_dump)
        if _is_trusted_output_handler(handler):
            handler_values = _handler_values(handler)
            if handler_values is not None:
                handler_values.pop("emit", None)
            safe_emit = handler.emit

        def emit_then_close(record: logging.LogRecord) -> None:
            try:
                if safe_emit is not None:
                    safe_emit(record)
            except Exception:
                _handle_error_without_record_dump(record)
            finally:
                try:
                    handler.close()
                except Exception:
                    pass

        object.__setattr__(handler, "emit", emit_then_close)
    finally:
        logging.Handler.release(handler)
    logger.removeHandler(handler)
    try:
        handler.close()
    except Exception:
        pass


def _handler_flag(handler: logging.Handler, attribute: str) -> bool:
    handler_values = _handler_values(handler)
    if handler_values is None:
        return False
    return handler_values.get(attribute) is True


def _resolved_handler_path(handler: logging.Handler) -> Path | None:
    if not _is_actual_instance(handler, logging.FileHandler):
        return None
    handler_values = _handler_values(handler)
    if handler_values is None:
        return None
    base_filename = handler_values.get("baseFilename")
    if type(base_filename) is not str or not base_filename:
        return None
    try:
        return Path(base_filename).resolve()
    except (OSError, RuntimeError, ValueError):
        return None


def _append_candidate_log_path(
    candidates: list[tuple[Path, Path, bool]],
    resolved_paths: set[Path],
    factory: Callable[[], Path],
    *,
    is_fallback: bool,
) -> None:
    try:
        log_path = factory()
        resolved_path = log_path.resolve()
    except (OSError, RuntimeError, ValueError):
        return
    if resolved_path in resolved_paths:
        return
    candidates.append((log_path, resolved_path, is_fallback))
    resolved_paths.add(resolved_path)


def _candidate_log_paths() -> tuple[list[tuple[Path, Path, bool]], set[Path]]:
    candidates: list[tuple[Path, Path, bool]] = []
    resolved_paths: set[Path] = set()
    factories = (
        (lambda: Path.home() / ".metroliza" / LOG_FILE_NAME, False),
        (lambda: Path.cwd() / LOG_FILE_NAME, False),
        (lambda: Path(tempfile.gettempdir()) / "metroliza" / LOG_FILE_NAME, True),
    )
    for factory, is_fallback in factories:
        _append_candidate_log_path(
            candidates,
            resolved_paths,
            factory,
            is_fallback=is_fallback,
        )
    return candidates, resolved_paths


def _remove_stale_file_handlers(
    logger: logging.Logger,
    allowed_paths: set[Path],
    formatter: logging.Formatter,
) -> None:
    for handler in list(logger.handlers):
        resolved_path = _resolved_handler_path(handler)
        if resolved_path is None:
            if _handler_flag(handler, "_metroliza_file_handler"):
                _remove_handler(logger, handler, formatter)
            continue
        is_metroliza_handler = (
            _handler_flag(handler, "_metroliza_file_handler")
            or resolved_path.name == LOG_FILE_NAME
        )
        if is_metroliza_handler and resolved_path not in allowed_paths:
            _remove_handler(logger, handler, formatter)


def _file_handlers_for_path(logger: logging.Logger, path: Path) -> list[logging.Handler]:
    return [
        handler
        for handler in logger.handlers
        if _resolved_handler_path(handler) == path
    ]


def _configure_one_file_handler(
    logger: logging.Logger,
    formatter: logging.Formatter,
    file_level: int,
    log_path: Path,
    resolved_path: Path,
) -> bool:
    matching_handlers = _file_handlers_for_path(logger, resolved_path)
    safe_handler = next(
        (
            candidate
            for candidate in matching_handlers
            if (
                type(candidate) is _SafeRotatingFileHandler
                or (
                    _is_actual_instance(
                        candidate,
                        logging.handlers.RotatingFileHandler,
                    )
                    and not _is_actual_instance(
                        candidate,
                        _SafeRotatingFileHandler,
                    )
                )
            )
            and (candidate_values := _handler_values(candidate)) is not None
            and type(candidate_values.get("maxBytes")) is int
            and candidate_values.get("maxBytes") == _FILE_MAX_BYTES
            and type(candidate_values.get("backupCount")) is int
            and candidate_values.get("backupCount") == _FILE_BACKUP_COUNT
        ),
        None,
    )
    for duplicate in matching_handlers:
        if duplicate is not safe_handler:
            _remove_handler(logger, duplicate, formatter)

    new_handler = safe_handler is None
    if new_handler:
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            safe_handler = _SafeRotatingFileHandler(
                str(log_path),
                maxBytes=_FILE_MAX_BYTES,
                backupCount=_FILE_BACKUP_COUNT,
                encoding="utf-8",
            )
        except OSError:
            return False

    assert safe_handler is not None
    object.__setattr__(safe_handler, "_metroliza_file_handler", True)
    logging.Handler.setLevel(safe_handler, file_level)
    _harden_handler(safe_handler, formatter)
    if new_handler:
        logger.addHandler(safe_handler)
    return True


def _configure_file_handlers(
    logger: logging.Logger,
    formatter: logging.Formatter,
    file_level: int,
) -> int:
    """Ensure managed file handlers exist and use expected rotation settings.

    Existing Metroliza-managed handlers that target unexpected paths are removed.
    Handlers at target paths are replaced when they are not rotating handlers or
    when their rotation parameters differ from expected values.
    """

    candidate_paths, resolved_paths = _candidate_log_paths()
    _remove_stale_file_handlers(logger, resolved_paths, formatter)

    configured_handlers = 0
    for log_path, resolved_path, is_fallback in candidate_paths:
        if is_fallback and configured_handlers > 0:
            for handler in _file_handlers_for_path(logger, resolved_path):
                _remove_handler(logger, handler, formatter)
            continue
        configured_handlers += int(
            _configure_one_file_handler(
                logger,
                formatter,
                file_level,
                log_path,
                resolved_path,
            )
        )

    return configured_handlers


def _configure_console_handler(
    logger: logging.Logger,
    formatter: logging.Formatter,
    console_level: int | None,
) -> bool:
    """Ensure a managed console handler matches the requested configuration.

    Args:
        logger: Logger to modify.
        formatter: Formatter to apply to the managed console handler.
        console_level: Desired console threshold, or ``None`` to remove the
            managed console handler.
    """

    console_handlers = [
        handler
        for handler in logger.handlers
        if _is_actual_instance(handler, logging.StreamHandler)
        and not _is_actual_instance(handler, logging.FileHandler)
        and _handler_flag(handler, "_metroliza_console_handler")
    ]

    if console_level is None:
        for handler in console_handlers:
            _remove_handler(logger, handler, formatter)
        return False

    console_handler = next(
        (
            handler
            for handler in console_handlers
            if type(handler) is _SafeStreamHandler
            or not _is_actual_instance(handler, _SafeStreamHandler)
        ),
        None,
    )
    for duplicate in console_handlers:
        if duplicate is not console_handler:
            _remove_handler(logger, duplicate, formatter)

    new_handler = console_handler is None
    if new_handler:
        console_handler = _SafeStreamHandler()

    assert console_handler is not None
    object.__setattr__(console_handler, "_metroliza_console_handler", True)
    logging.Handler.setLevel(console_handler, console_level)
    _harden_handler(console_handler, formatter)
    if new_handler:
        logger.addHandler(console_handler)
    return True


def _configure_safe_fallback_handler(
    logger: logging.Logger,
    formatter: logging.Formatter,
    *,
    needed: bool,
) -> None:
    fallback_handlers = [
        handler
        for handler in logger.handlers
        if _handler_flag(handler, "_metroliza_safe_fallback_handler")
    ]
    if not needed:
        for handler in fallback_handlers:
            _remove_handler(logger, handler, formatter)
        return

    fallback_handler = next(
        (handler for handler in fallback_handlers if type(handler) is _SafeStreamHandler),
        None,
    )
    for duplicate in fallback_handlers:
        if duplicate is not fallback_handler:
            _remove_handler(logger, duplicate, formatter)

    new_handler = fallback_handler is None
    if new_handler:
        fallback_handler = _SafeStreamHandler()

    assert fallback_handler is not None
    object.__setattr__(fallback_handler, "_metroliza_safe_fallback_handler", True)
    logging.Handler.setLevel(fallback_handler, logging.WARNING)
    _harden_handler(fallback_handler, formatter)
    if new_handler:
        logger.addHandler(fallback_handler)


def ensure_application_logging(
    config: LoggingConfig | None = None,
    level: int | None = None,
) -> LoggingConfig:
    """Apply resolved logging configuration to the root logger.

    Args:
        config: Optional pre-resolved logging configuration. When omitted,
            :func:`resolve_logging_config` is used.
        level: Optional override for root and file levels when ``config`` is not
            provided. Console level still follows resolved environment behavior.

    Returns:
        The effective :class:`LoggingConfig` applied to logging.

    Notes:
        Records already handed to independently consumed queues or executing
        custom ``handle`` overrides before this call cannot be recalled. Handler
        registration is replaced with a safe empty boundary before preexisting
        handlers are hardened, and locally pending buffering-handler records are
        sanitized during that transition. The application boundary applies once
        a record enters a hardened handler.

        The stdlib constructs each :class:`logging.LogRecord` before handler
        dispatch and may inspect argument protocols while doing so. That
        pre-handler record-construction behavior is outside this boundary; once
        a record exists, sanitization reads actual built-in types without using
        instance ``__class__`` or formatting hooks.

        Filters reached through the standard :class:`logging.Handler` contract
        continue to see the original template and arguments. Custom ``handle``
        overrides receive a template-shaped safe record with textual argument
        values redacted. Handler ``emit`` and ``handleError`` methods receive a
        sanitized base record with resolved text, empty arguments, and
        message-free exception and stack structure.
    """
    with _CONFIGURATION_LOCK:
        logger = logging.getLogger()
        formatter = _RedactingFormatter(
            "%(asctime)s %(levelname)s [%(name)s] [%(threadName)s] %(message)s"
        )
        _secure_last_resort(formatter)
        existing_handlers = _detach_existing_handlers(logger, formatter)
        _secure_existing_handlers(logger, formatter, existing_handlers)

        resolved_config = config or resolve_logging_config()
        if level is not None and config is None:
            resolved_config = LoggingConfig(
                global_level=level,
                file_level=level,
                console_level=resolved_config.console_level,
            )
        logger.setLevel(resolved_config.global_level)

        file_handler_count = _configure_file_handlers(
            logger,
            formatter,
            resolved_config.file_level,
        )
        console_enabled = _configure_console_handler(
            logger,
            formatter,
            resolved_config.console_level,
        )
        _configure_safe_fallback_handler(
            logger,
            formatter,
            needed=file_handler_count == 0 and not console_enabled,
        )

        return resolved_config
