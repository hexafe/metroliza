"""File identity for controlled benchmarks using ordinary CPython imports.

Trust the interpreter and installed environment. Reject checkout native builds;
record installed extension bytes, aliases and origins before imports, then check
again outside each timed request. This is checkpoint evidence, not an OS sandbox
or attestation of transitive shared libraries or hostile file/loader activity.
"""
from __future__ import annotations

import hashlib
import importlib.machinery as machinery
import os
from pathlib import Path
import platform
import sys
import time

BRIDGE_NAMES = (
    "_metroliza_chart_native", "_metroliza_group_stats_native",
    "_metroliza_comparison_stats_native", "_metroliza_distribution_fit_native",
    "_metroliza_cmm_native", "_hexafe_groupstats_native",
)
# Also recognize foreign ABI variants conservatively; never execute to identify.
NATIVE_ENDINGS = (".so", ".pyd")


class NativeInputError(BaseException):
    """Cannot be swallowed by application optional-backend Exception fallbacks."""


def _absolute(path) -> Path:
    return Path(os.path.abspath(path))


def _native_file(path: Path) -> bool:
    # Windows FileFinder normalizes suffix case, but preserves the module basename.
    return path.name.lower().endswith(NATIVE_ENDINGS) and path.name.split(".")[0].isidentifier()


def _candidates(root: Path, ancestors: frozenset[Path] = frozenset()):
    """Walk only import-addressable directories, including namespace packages."""
    resolved = root.resolve(strict=True)
    if resolved in ancestors:
        raise RuntimeError("Unsupported cyclic import-directory symlink")
    for child in sorted(root.iterdir()):
        if _native_file(child):
            if not child.is_file():
                raise RuntimeError("Missing or nonregular native input: " + str(child))
            yield child
        elif child.name.isidentifier() and child.is_dir():
            yield from _candidates(child, ancestors | {resolved})


def reject_checkout_native(repo: Path) -> None:
    # root includes src and namespace/package directories, independent of Git.
    if next(_candidates(repo), None) is not None:
        raise RuntimeError("Checkout-local native inputs are unsupported; use a clean separate "
                           "checkout without moving or deleting user build artifacts")


def _fingerprint(path: Path) -> dict:
    resolved = path.resolve(strict=True)
    if not resolved.is_file():
        raise RuntimeError("Native input must be a readable regular file")
    digest = hashlib.sha256()
    with resolved.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return {"resolved_path": str(resolved), "sha256": digest.hexdigest(),
            "size": resolved.stat().st_size}


class NativeProvenance:
    """Inventory admitted sys.path roots and verify standard extension imports.

    Construct before application imports, then install in a fresh worker. Hashing
    and inventories happen only in construction/verify, outside workflow timing.
    The import audit hook checks membership without reading/hashing file content.
    Custom native loaders or origins outside the captured roots fail closed.
    """

    def __init__(self, repo: Path):
        started = time.perf_counter()
        if sys.implementation.name != "cpython":
            raise RuntimeError("Native provenance requires CPython import audit events")
        self.platform_identity = platform.platform()
        self.repo = repo.resolve()
        reject_checkout_native(self.repo)
        self.search_path = tuple(sys.path)
        self.roots = []
        for index, item in enumerate(self.search_path):
            root = _absolute(item or os.getcwd())
            if not root.exists():
                # CPython normally includes a nonexistent pythonXY.zip entry.
                continue
            if not root.is_dir():
                raise RuntimeError("Unsupported non-directory import root: " + str(root))
            self.roots.append((f"sys-path-{index}", root))
        self.inventory = self._inventory()
        self.by_resolved = {record["resolved_path"]: record
                            for record in self.inventory.values()}
        self.interpreter = _fingerprint(Path(sys.executable))
        self.resolutions = self._bridge_resolutions()
        self.observed_loads: dict[str, str] = {}
        self.loaded = self._loaded()
        self.bridge_loaded = self._loaded_bridges()
        self.initially_loaded = sorted(self.loaded)
        self.verification_s = time.perf_counter() - started
        self.checkpoints = 0
        self._installed = False
        self.import_guard_s = 0.0

    def _inventory(self) -> dict:
        result = {}
        fingerprints = {}
        for label, root in self.roots:
            for path in _candidates(root):
                absolute = _absolute(path)
                resolved = path.resolve(strict=True)
                if absolute.is_relative_to(self.repo) or resolved.is_relative_to(self.repo):
                    raise RuntimeError("Checkout-local native input or alias is unsupported")
                if resolved not in fingerprints:
                    fingerprints[resolved] = _fingerprint(path)
                key = label + "/" + path.relative_to(root).as_posix()
                result[key] = {"logical_origin": key, "path": str(absolute),
                               **fingerprints[resolved]}
        return result

    def _bridge_resolutions(self) -> dict:
        resolutions = {}
        for name in BRIDGE_NAMES:
            spec = machinery.PathFinder.find_spec(name, list(self.search_path))
            if spec is None:
                resolutions[name] = None
                continue
            if not isinstance(spec.loader, (machinery.ExtensionFileLoader,
                                            machinery.SourceFileLoader)):
                raise RuntimeError("Unsupported native bridge loader: " + name)
            origin = str(Path(spec.origin).resolve(strict=True))
            if isinstance(spec.loader, machinery.ExtensionFileLoader) and origin not in self.by_resolved:
                raise RuntimeError("Unidentified native bridge origin: " + name)
            resolutions[name] = {**_fingerprint(Path(spec.origin)),
                                 "loader": type(spec.loader).__name__,
                                 "package_paths": list(spec.submodule_search_locations or ())}
        return resolutions

    def _loaded_bridges(self) -> dict:
        result = {}
        for name, expected in self.resolutions.items():
            module = sys.modules.get(name)
            if module is None:
                result[name] = None
                continue
            spec = getattr(module, "__spec__", None)
            origin = getattr(spec, "origin", None)
            filename = getattr(module, "__file__", None)
            if (not expected or not filename or not origin
                    or str(Path(filename).resolve(strict=True)) != expected["resolved_path"]
                    or str(Path(origin).resolve(strict=True)) != expected["resolved_path"]
                    or type(spec.loader).__name__ != expected["loader"]):
                raise RuntimeError("Loaded native bridge origin mismatch: " + name)
            result[name] = expected["resolved_path"]
        return result

    def _loaded(self) -> dict:
        loaded = {}
        exports = []
        for name, module in tuple(sys.modules.items()):
            spec = getattr(module, "__spec__", None)
            origin = getattr(spec, "origin", None)
            filename = getattr(module, "__file__", None)
            is_extension = isinstance(getattr(spec, "loader", None), machinery.ExtensionFileLoader)
            if not is_extension and not (filename and _native_file(Path(filename))):
                continue
            if not is_extension:
                if getattr(spec, "loader", None) is not None or getattr(module, "__loader__", None) is not None:
                    raise RuntimeError("Unsupported loaded native module: " + name)
                exports.append((name, module, filename))
                continue
            if not origin or not filename:
                raise RuntimeError("Unsupported loaded native module: " + name)
            actual = str(Path(filename).resolve(strict=True))
            if actual != str(Path(origin).resolve(strict=True)) or actual not in self.by_resolved:
                raise RuntimeError("Loaded native origin mismatch: " + name)
            resolution_name = spec.name
            if sys.modules.get(resolution_name) is not module:
                raise RuntimeError("Native alias has no matching canonical module: " + name)
            parent = resolution_name.rpartition(".")[0]
            search = getattr(sys.modules.get(parent), "__path__", None) if parent else list(sys.path)
            resolved = machinery.PathFinder.find_spec(resolution_name, search)
            if (resolved is None or not isinstance(resolved.loader, machinery.ExtensionFileLoader)
                    or str(Path(resolved.origin).resolve(strict=True)) != actual):
                raise RuntimeError("Loaded native origin disagrees with import resolution: " + name)
            loaded[name] = {"kind": "extension", "origin": actual,
                            "loaded_path": str(_absolute(filename)), "resolution_name": resolution_name,
                            "artifact": self.by_resolved[actual]["logical_origin"]}
        loaded.update(self._native_exports(exports, loaded))
        return loaded

    def _native_exports(self, exports, loaded) -> dict:
        providers = {record["resolution_name"]: record for record in loaded.values()}
        result = {}
        for name, module, filename in exports:
            canonical = getattr(module, "__name__", "")
            if sys.modules.get(canonical) is not module:
                raise RuntimeError("Native export has no matching canonical module: " + name)
            parent = canonical.rpartition(".")[0]
            while parent and parent not in providers:
                parent = parent.rpartition(".")[0]
            if not parent:
                raise RuntimeError("Native export has no verified provider: " + name)
            owner = sys.modules[parent]
            for component in canonical[len(parent) + 1:].split("."):
                owner = vars(owner).get(component) if isinstance(owner, type(sys)) else None
            actual = str(Path(filename).resolve(strict=True))
            spec = getattr(module, "__spec__", None)
            origin = getattr(spec, "origin", None)
            if (owner is not module or actual != providers[parent]["origin"]
                    or (spec is not None and spec.name != canonical)
                    or (origin is not None and str(Path(origin).resolve(strict=True)) != actual)):
                raise RuntimeError("Native export disagrees with verified provider: " + name)
            result[name] = {"kind": "native_export", "provider": parent, "origin": actual,
                            "loaded_path": str(_absolute(filename)), "canonical_name": canonical,
                            "artifact": providers[parent]["artifact"]}
        return result

    def install(self) -> None:
        if self._installed:
            raise RuntimeError("Native provenance audit already installed")
        self._installed = True

        def audit(event, args):
            if event != "import" or len(args) < 2 or not args[1]:
                return
            checked_at = time.perf_counter()
            try:
                path = Path(args[1])
                origin = str(path.resolve())
                if origin not in self.by_resolved:
                    raise NativeInputError("Unidentified native input before import: " + args[0])
                previous = self.observed_loads.setdefault(args[0], origin)
                if previous != origin:
                    raise NativeInputError("Native import origin changed: " + args[0])
            finally:
                self.import_guard_s += time.perf_counter() - checked_at

        sys.addaudithook(audit)

    def verify(self) -> dict:
        started = time.perf_counter()
        if tuple(sys.path) != self.search_path:
            raise RuntimeError("Benchmark import search path changed")
        # Re-evaluate existence of initially absent search roots as well.
        current_roots = [(f"sys-path-{i}", _absolute(p or os.getcwd()))
                         for i, p in enumerate(sys.path) if _absolute(p or os.getcwd()).exists()]
        if current_roots != self.roots or self._inventory() != self.inventory:
            raise RuntimeError("Native input inventory/content changed during measurement")
        if _fingerprint(Path(sys.executable)) != self.interpreter:
            raise RuntimeError("Benchmark interpreter changed")
        if self._bridge_resolutions() != self.resolutions:
            raise RuntimeError("Native bridge resolution changed")
        self._verify_loaded_origins()
        self.checkpoints += 1
        self.verification_s += time.perf_counter() - started
        return self.receipt()

    def _verify_loaded_origins(self) -> None:
        loaded = self._loaded()
        bridges = self._loaded_bridges()
        for name, previous in self.bridge_loaded.items():
            if previous is not None and bridges[name] != previous:
                raise RuntimeError("Loaded native bridge removed or replaced: " + name)
        self.bridge_loaded = bridges
        for name, previous in self.loaded.items():
            if loaded.get(name) != previous:
                raise RuntimeError("Loaded native module removed or replaced: " + name)
        for name, origin in self.observed_loads.items():
            if loaded.get(name, {}).get("origin") != origin:
                raise RuntimeError("Audited native import disagrees with loaded origin: " + name)
        self.loaded = loaded

    def receipt(self) -> dict:
        return {
            "policy": "trusted-environment-checkpoint-v1; reject checkout native builds",
            "search_roots": [{"logical_root": label, "path": str(root),
                              "resolved_path": str(root.resolve())} for label, root in self.roots],
            "artifacts": self.inventory, "bridge_resolution": self.resolutions,
            "loaded_extensions": self.loaded, "loaded_bridges": self.bridge_loaded,
            "initially_loaded": self.initially_loaded,
            "observed_native_imports": self.observed_loads,
            "computational_use": "not inferred from availability or import",
            "requested_backend_environment": {key: value for key, value in sorted(os.environ.items())
                                               if key.startswith("METROLIZA_") and "BACKEND" in key},
            "interpreter": {**self.interpreter, "version": sys.version,
                            "platform": self.platform_identity, "cache_tag": sys.implementation.cache_tag,
                            "builtin_modules": sys.builtin_module_names,
                            "extension_suffixes": machinery.EXTENSION_SUFFIXES},
            "artifact_build_source_identity": "not attested; content identity only",
            "import_guard_s": self.import_guard_s,
            "verification_s": self.verification_s, "checkpoints": self.checkpoints,
        }
