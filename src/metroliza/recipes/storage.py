"""Private, bounded recipe persistence with atomic revision-checked replacement."""
from __future__ import annotations

import json
import os
import stat
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Iterator
from uuid import UUID, uuid4

from metroliza.shared.local_app_paths import local_metroliza_directory

from .contracts import (
    FORMAT_VERSION, MAX_PAYLOAD_BYTES, DataKind, DerivationRule, LocalBinding, ParameterKey, ParameterMode,
    ParameterSpec, ParameterType, RecipeDefinition, RecipeError, StepKind, StepSpec,
)
from .validation import validate_binding

MAX_RECIPES = 256


@dataclass(frozen=True, repr=False)
class StoredRecipe:
    definition: RecipeDefinition
    binding: LocalBinding


@dataclass(frozen=True, repr=False)
class RecipeLoadIssue:
    filename: str
    code: str


def default_store_directory() -> Path:
    return local_metroliza_directory() / "recipes"


def definition_payload(definition: RecipeDefinition) -> dict[str, Any]:
    """Portable structure deliberately has no names, revision, or private values."""
    return {
        "format_version": definition.format_version, "method_version": definition.method_version,
        "recipe_id": definition.recipe_id, "builtin": definition.builtin,
        "steps": [{"kind": s.kind.value, "input_kind": s.input_kind.value,
                   "output_kind": s.output_kind.value} for s in definition.steps],
        "parameters": [{"key": p.key.value, "type": p.type.value, "mode": p.mode.value,
                        "required": p.required, "rule": p.rule.value if p.rule else None}
                       for p in definition.parameters],
    }


def _keys(value: Any, keys: set[str]) -> dict[str, Any]:
    if type(value) is not dict or set(value) != keys:
        raise RecipeError("unknown_keys")
    return value


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise RecipeError("duplicate_json_key")
        result[key] = value
    return result


def _decode(raw: bytes) -> StoredRecipe:
    try:
        payload = json.loads(raw, object_pairs_hook=_unique_object)
        definition_header = payload.get("definition") if isinstance(payload, dict) else None
        version = definition_header.get("format_version") if isinstance(definition_header, dict) else None
        if type(version) is int and version > FORMAT_VERSION:
            raise RecipeError("newer_format")
        _keys(payload, {"definition", "binding"})
        d = _keys(payload["definition"], {"format_version", "method_version", "recipe_id",
            "builtin", "steps", "parameters"})
        if type(d["steps"]) is not list or type(d["parameters"]) is not list:
            raise RecipeError("invalid_definition")
        steps = []
        for s in d["steps"]:
            _keys(s, {"kind", "input_kind", "output_kind"})
            steps.append(StepSpec(StepKind(s["kind"]), DataKind(s["input_kind"]),
                                  DataKind(s["output_kind"])))
        parameters = []
        for p in d["parameters"]:
            _keys(p, {"key", "type", "mode", "required", "rule"})
            parameters.append(ParameterSpec(ParameterKey(p["key"]), ParameterType(p["type"]),
                ParameterMode(p["mode"]), p["required"],
                DerivationRule(p["rule"]) if p["rule"] is not None else None))
        definition = RecipeDefinition(d["recipe_id"], tuple(steps), tuple(parameters),
                                      d["format_version"], d["method_version"], d["builtin"])
        b = _keys(payload["binding"], {"recipe_id", "name", "revision", "values"})
        if type(b["values"]) is not dict:
            raise RecipeError("invalid_binding")
        values = tuple((ParameterKey(k), tuple(v) if type(v) is list else v)
                       for k, v in b["values"].items())
        binding = LocalBinding(b["recipe_id"], b["name"], b["revision"], values)
        validate_binding(definition, binding)
        if definition.builtin:
            raise RecipeError("builtin_read_only")
        return StoredRecipe(definition, binding)
    except RecipeError:
        raise
    except (ValueError, TypeError, KeyError, RecursionError, AttributeError) as exc:
        raise RecipeError("invalid_recipe_file") from exc


class RecipeStore:
    def __init__(self, root: Path | None = None, *, forbidden_roots: tuple[Path, ...] = ()):
        self.root = Path(root) if root is not None else default_store_directory()
        candidate = self.root.resolve(strict=False)
        for forbidden in forbidden_roots:
            if candidate == forbidden.resolve() or forbidden.resolve() in candidate.parents:
                raise RecipeError("private_location_required")

    def _ensure_root(self) -> None:
        if self.root.is_symlink():
            raise RecipeError("unsafe_store")
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if not self.root.is_dir():
            raise RecipeError("unsafe_store")
        if os.name != "nt":
            os.chmod(self.root, 0o700)

    def _path(self, recipe_id: str) -> Path:
        try:
            normalized = str(UUID(recipe_id))
        except (ValueError, TypeError, AttributeError) as exc:
            raise RecipeError("invalid_recipe_id") from exc
        return self.root / f"{normalized}.json"

    @contextmanager
    def _lock(self) -> Iterator[None]:
        self._ensure_root()
        path = self.root / ".write.lock"
        if path.is_symlink():
            raise RecipeError("unsafe_store")
        flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(path, flags, 0o600)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise RecipeError("unsafe_store")
            try:
                if os.name == "nt":
                    import msvcrt
                    if os.fstat(fd).st_size == 0:
                        os.write(fd, b"0")
                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise RecipeError("store_busy") from exc
            yield
        finally:
            # Closing releases the OS lock, including after process termination.
            os.close(fd)

    def load(self, recipe_id: str) -> StoredRecipe:
        path = self._path(recipe_id)
        if self.root.is_symlink() or path.is_symlink():
            raise RecipeError("unsafe_store")
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) |
                     getattr(os, "O_NONBLOCK", 0))
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise RecipeError("unsafe_store")
            with os.fdopen(fd, "rb", closefd=False) as stream:
                raw = stream.read(MAX_PAYLOAD_BYTES + 1)
        finally:
            os.close(fd)
        if len(raw) > MAX_PAYLOAD_BYTES:
            raise RecipeError("payload_limit")
        stored = _decode(raw)
        if str(UUID(stored.definition.recipe_id)) != path.stem:
            raise RecipeError("binding_identity")
        return stored

    def list(self) -> tuple[StoredRecipe, ...]:
        return self.scan()[0]

    def scan(self) -> tuple[tuple[StoredRecipe, ...], tuple[RecipeLoadIssue, ...]]:
        """Read each catalog entry independently and keep damage local to its filename."""
        if self.root.is_symlink():
            raise RecipeError("unsafe_store")
        paths = sorted(self.root.glob("*.json"))
        if len(paths) > MAX_RECIPES:
            raise RecipeError("recipe_count_limit")
        recipes = []
        issues = []
        for path in paths:
            try:
                if self._path(path.stem) != path:
                    raise RecipeError("invalid_recipe_id")
                recipes.append(self.load(path.stem))
            except RecipeError as exc:
                issues.append(RecipeLoadIssue(path.name, exc.code))
            except OSError:
                issues.append(RecipeLoadIssue(path.name, "unreadable_recipe_file"))
        return tuple(recipes), tuple(issues)

    def _validate_save(self, definition: RecipeDefinition, binding: LocalBinding,
                       expected_revision: int | None) -> None:
        validate_binding(definition, binding)
        candidate = self.root.resolve(strict=False)
        for key in (ParameterKey.INPUT_FOLDER, ParameterKey.SOURCE_FILE):
            raw_source = binding.value(key)
            if raw_source:
                source = Path(str(raw_source)).expanduser().resolve(strict=False)
                folder = source.parent if key is ParameterKey.SOURCE_FILE else source
                if candidate == folder or folder in candidate.parents:
                    raise RecipeError("private_location_required")
        for raw_source in binding.value(ParameterKey.SOURCE_FILES, ()):
            folder = Path(raw_source).expanduser().resolve(strict=False).parent
            if candidate == folder or folder in candidate.parents:
                raise RecipeError("private_location_required")
        if definition.builtin:
            raise RecipeError("builtin_read_only")
        if expected_revision is not None and (type(expected_revision) is not int or expected_revision < 1):
            raise RecipeError("binding_revision")

    def _next_revision(self, path: Path, binding: LocalBinding,
                       expected_revision: int | None) -> int:
        if path.exists() or path.is_symlink():
            current = self.load(binding.recipe_id)
            if expected_revision != current.binding.revision or binding.revision != expected_revision:
                raise RecipeError("revision_conflict")
            return current.binding.revision + 1
        if expected_revision is not None or binding.revision != 0:
            raise RecipeError("revision_conflict")
        if len(tuple(self.root.glob("*.json"))) >= MAX_RECIPES:
            raise RecipeError("recipe_count_limit")
        return 1

    @staticmethod
    def _encode(definition: RecipeDefinition, binding: LocalBinding) -> bytes:
        payload = {"definition": definition_payload(definition), "binding": {
            "recipe_id": binding.recipe_id, "name": binding.name, "revision": binding.revision,
            "values": {k.value: v for k, v in binding.values}}}
        raw = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()
        if len(raw) > MAX_PAYLOAD_BYTES:
            raise RecipeError("payload_limit")
        return raw

    def _sync_directory(self) -> None:
        if os.name == "nt":
            return
        directory = os.open(self.root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)

    def _atomic_replace(self, path: Path, raw: bytes) -> None:
        fd, temporary = tempfile.mkstemp(prefix=".recipe-", suffix=".tmp", dir=self.root)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            self._sync_directory()
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def save(self, definition: RecipeDefinition, binding: LocalBinding, *,
             expected_revision: int | None) -> StoredRecipe:
        self._validate_save(definition, binding, expected_revision)
        with self._lock():
            path = self._path(definition.recipe_id)
            revision = self._next_revision(path, binding, expected_revision)
            updated = replace(binding, revision=revision)
            self._atomic_replace(path, self._encode(definition, updated))
            return StoredRecipe(definition, updated)


def copy_recipe(definition: RecipeDefinition, binding: LocalBinding, *, name: str) -> StoredRecipe:
    identity = str(uuid4())
    copied = replace(definition, recipe_id=identity, builtin=False)
    local = replace(binding, recipe_id=identity, name=name, revision=0)
    validate_binding(copied, local)
    return StoredRecipe(copied, local)
