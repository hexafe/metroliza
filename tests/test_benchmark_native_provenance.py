"""Native attribution regressions use fresh interpreters; inert files never execute."""
from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import py_compile
import subprocess
import sys
from textwrap import dedent

import pytest

ROOT = Path(__file__).resolve().parents[1]
SUFFIXES = tuple(dict.fromkeys([
    *importlib.machinery.EXTENSION_SUFFIXES, ".so", ".pyd", ".PYD",
    *(suffix.upper() for suffix in importlib.machinery.EXTENSION_SUFFIXES),
]))


def _child(tmp_path, code, *args):
    result = subprocess.run(
        [sys.executable, "-I", "-B", "-c", "import sys\nfrom pathlib import Path\n"
         "sys.path.insert(0, sys.argv[1])\n" + dedent(code), str(ROOT), *map(str, args)],
        cwd=tmp_path, capture_output=True, text=True, timeout=90,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


@pytest.mark.parametrize("location", [".", "src"])
@pytest.mark.parametrize("suffix", SUFFIXES)
def test_ignored_importable_native_is_rejected_before_execution(tmp_path, location, suffix):
    _child(tmp_path, """\
        import importlib.machinery as machinery
        import subprocess
        from scripts.benchmark_csv_pipeline import _checkout_identity
        repo = Path(sys.argv[2])
        location, suffix = sys.argv[3:]
        repo.mkdir()
        def git(*args):
            return subprocess.check_output(['git', *args], cwd=repo, text=True)
        git('init', '--quiet')
        (repo / '.gitignore').write_text('*.[sS][oO]\\n*.[pP][yY][dD]\\n')
        git('add', '.gitignore')
        git('-c', 'user.name=Test', '-c', 'user.email=test@example.invalid',
            'commit', '--quiet', '-m', 'inert fixture')
        directory = repo / location
        directory.mkdir(exist_ok=True)
        artifact = directory / ('_metroliza_group_stats_native' + suffix)
        artifact.write_bytes(b'INERT - MUST NEVER EXECUTE')
        assert git('status', '--porcelain') == ''
        assert git('check-ignore', str(artifact)).strip()
        if suffix in machinery.EXTENSION_SUFFIXES or (
            sys.platform == 'win32' and suffix.lower() in machinery.EXTENSION_SUFFIXES
        ):
            spec = machinery.PathFinder.find_spec('_metroliza_group_stats_native', [str(directory)])
            assert Path(spec.origin) == artifact
            assert isinstance(spec.loader, machinery.ExtensionFileLoader)
        try:
            _checkout_identity(repo)
        except RuntimeError as exc:
            assert 'native' in str(exc).lower()
        else:
            raise AssertionError('Ignored native input incorrectly attributed to clean Git identity')
        assert artifact.read_bytes() == b'INERT - MUST NEVER EXECUTE'
        assert '_metroliza_group_stats_native' not in sys.modules
        print('GIT_IGNORED_NATIVE_REJECTED')
        """, tmp_path / "repo", location, suffix)


GUARD_SETUP = """\
from scripts.benchmark_native_provenance import NativeProvenance, NativeInputError
import os
import importlib
import importlib.util
import importlib.machinery as machinery
import hashlib
repo = Path(sys.argv[2]); repo.mkdir()
external = Path(sys.argv[3]); external.mkdir()
sys.path.remove(sys.argv[1])
sys.path.insert(0, str(external))
"""


def _guard_child(tmp_path, code, *args):
    return _child(tmp_path, GUARD_SETUP + dedent(code), *args)


def _bootstrap_child(tmp_path, location, suffix, option="tooling", link=False, module="argparse"):
    _child(tmp_path, """\
        import builtins
        import importlib.machinery as machinery
        import subprocess
        import os
        location, suffix, option, link, module = sys.argv[3:]
        tooling = Path(sys.argv[2]) / 'tooling'; (tooling / 'scripts').mkdir(parents=True)
        measured = tooling.parent / 'measured'; measured.mkdir()
        driver = tooling / 'scripts' / 'benchmark_csv_pipeline.py'
        driver.write_bytes((Path(sys.argv[1]) / 'scripts' / driver.name).read_bytes())
        selected = tooling if option == 'tooling' else measured
        directory = selected / location; directory.mkdir(exist_ok=True)
        artifact = directory / (module + suffix)
        if link == 'True':
            target = tooling.parent / 'native-target'; target.mkdir()
            (target / artifact.name).write_bytes(b'INERT - MUST NEVER EXECUTE')
            if location == 'linked':
                directory.rmdir(); directory.symlink_to(target, target_is_directory=True)
            else:
                artifact.symlink_to(target / artifact.name)
        else:
            artifact.write_bytes(b'INERT - MUST NEVER EXECUTE')
        (selected / '.gitignore').write_text('*.[sS][oO]\\n*.[pP][yY][dD]\\nlinked\\n')
        subprocess.run(['git', 'init', '--quiet', str(selected)], check=True)
        subprocess.run(['git', 'add', '.gitignore'], cwd=selected, check=True)
        subprocess.run(['git', '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid',
                        'commit', '--quiet', '-m', 'bootstrap fixture'], cwd=selected, check=True)
        ignored_entry = directory if link == 'True' and location == 'linked' else artifact
        assert subprocess.check_output(['git', 'check-ignore', str(ignored_entry)], cwd=selected)
        spec = machinery.PathFinder.find_spec(module, [str(directory)])
        if suffix in machinery.EXTENSION_SUFFIXES or (
            sys.platform == 'win32' and suffix.lower() in machinery.EXTENSION_SUFFIXES
        ):
            assert spec and Path(spec.origin) == artifact
            assert isinstance(spec.loader, machinery.ExtensionFileLoader)
        assert module not in sys.modules
        original_import = builtins.__import__
        def checked_import(name, *args, **kwargs):
            if name in {'argparse', 'cProfile', 'hashlib'}:
                raise AssertionError('Bootstrap dependency reached before native rejection: ' + name)
            return original_import(name, *args, **kwargs)
        builtins.__import__ = checked_import
        # Belt-and-braces: never initialize an inert candidate even if the first gate regresses.
        def audit(event, args):
            if event == 'import' and len(args) > 1 and args[1]:
                raise AssertionError('Unexpected native initialization in inert bootstrap test')
        sys.addaudithook(audit)
        sys.path[:0] = [str(directory), str(tooling / 'scripts'), str(tooling)]
        if option == 'tooling':
            arguments = ['--help']
        else:
            flag, style = option.split(':')
            value = str(measured) if '--repo'.startswith(flag) else 'B=' + str(measured)
            arguments = [flag + '=' + value] if style == 'equals' else [flag, value]
            arguments += ['--help']
        sys.argv = [str(driver), *arguments]
        try:
            exec(compile(driver.read_bytes(), str(driver), 'exec'),
                 {'__file__': str(driver), '__name__': '__main__', '__package__': None, '__spec__': None})
        except RuntimeError as exc:
            assert 'native' in str(exc).lower()
        else:
            raise AssertionError('Bootstrap accepted checkout native input')
        assert artifact.read_bytes() == b'INERT - MUST NEVER EXECUTE'
        """, tmp_path, location, suffix, option, link, module)


@pytest.mark.parametrize("location", [".", "src", "scripts"])
@pytest.mark.parametrize("suffix", SUFFIXES)
def test_bootstrap_native_rejection_precedes_stdlib_imports(tmp_path, location, suffix):
    _bootstrap_child(tmp_path, location, suffix)


@pytest.mark.parametrize("module", ["cProfile", "benchmark_native_provenance"])
def test_bootstrap_rejects_dependency_and_helper_shadows(tmp_path, module):
    _bootstrap_child(tmp_path, "scripts", importlib.machinery.EXTENSION_SUFFIXES[0], module=module)


@pytest.mark.parametrize("flag", ["--repo", "--rep", "--compare", "--compar", "--co"])
@pytest.mark.parametrize("style", ["equals", "separate"])
@pytest.mark.parametrize("location", [".", "src"])
def test_bootstrap_covers_declared_checkout_on_startup_path(tmp_path, flag, style, location):
    _bootstrap_child(tmp_path, location, importlib.machinery.EXTENSION_SUFFIXES[0], flag + ':' + style)


@pytest.mark.parametrize("location", [".", "linked"])
def test_bootstrap_native_symlinks_are_rejected(tmp_path, location):
    probe = tmp_path / "probe"
    try:
        probe.symlink_to(tmp_path, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation unavailable on this host")
    probe.unlink()
    _bootstrap_child(tmp_path, location, importlib.machinery.EXTENSION_SUFFIXES[0], link=True)


@pytest.mark.parametrize("flag", ["--repo", "--rep", "--compare", "--co"])
@pytest.mark.parametrize("equals", [False, True])
def test_bootstrap_roots_agree_with_accepted_cli(monkeypatch, tmp_path, flag, equals):
    from scripts import benchmark_csv_pipeline as driver

    first = str(tmp_path / "first")
    value = first if "--repo".startswith(flag) else "B=" + first
    arguments = [flag + "=" + value] if equals else [flag, value]
    if "--repo".startswith(flag):
        arguments.append("--worker")
    elif not equals:
        arguments.append("C=" + str(tmp_path / "second"))
    arguments += ["--output", str(tmp_path / "output")]
    captured = []
    monkeypatch.setattr(driver, "_worker", captured.append)
    monkeypatch.setattr(driver, "_compare", captured.append)
    monkeypatch.setattr(sys, "argv", [driver.__file__, *arguments])
    driver.main()
    args = captured[0]
    expected = [args.repo] if args.worker else [v.split("=", 1)[1] for v in args.compare]
    assert driver._bootstrap_roots(arguments)[1:] == expected
    assert driver._bootstrap_roots(["--", *arguments])[1:] == []


def test_bootstrap_file_symlink_uses_actual_interpreter_search_root(tmp_path):
    target = tmp_path / "source" / "scripts"
    target.mkdir(parents=True)
    invocation = tmp_path / "invocation"
    invocation.mkdir()
    probe = target / "probe.py"
    probe.write_text("import sys\nprint(sys.path[0])\n")
    link = invocation / "entry.py"
    try:
        link.symlink_to(probe)
    except OSError:
        pytest.skip("symlink creation unavailable on this host")
    observed = subprocess.check_output([sys.executable, str(link)], cwd=tmp_path, text=True).strip()
    link.unlink()
    driver = target / "benchmark_csv_pipeline.py"
    driver.write_bytes((ROOT / "scripts" / driver.name).read_bytes())
    link.symlink_to(driver)
    artifact = invocation / ("argparse" + importlib.machinery.EXTENSION_SUFFIXES[0])
    artifact.write_bytes(b"INERT - MUST NEVER EXECUTE")
    output = _child(tmp_path, """\
        import importlib.machinery as machinery
        import os
        link, observed, artifact = map(Path, sys.argv[2:])
        admitted = observed.resolve() == link.parent.resolve()
        spec = machinery.PathFinder.find_spec('argparse', [str(artifact.parent)])
        assert Path(spec.origin) == artifact and isinstance(spec.loader, machinery.ExtensionFileLoader)
        assert 'argparse' not in sys.modules
        def audit(event, args):
            if event == 'import' and len(args) > 1 and args[1]:
                assert Path(args[1]).resolve() != artifact.resolve(), 'Inert binary reached loader'
        sys.addaudithook(audit)
        sys.path[0] = str(observed)
        sys.argv = [str(link), '--help']
        try:
            exec(compile(link.read_bytes(), str(link), 'exec'),
                 {'__file__': str(link), '__name__': '__main__', '__package__': None, '__spec__': None})
        except RuntimeError as exc:
            assert admitted and 'native' in str(exc).lower()
        except SystemExit as exc:
            assert not admitted and exc.code == 0
        else:
            raise AssertionError('No bootstrap disposition')
        assert artifact.read_bytes() == b'INERT - MUST NEVER EXECUTE'
        print('FILE_SYMLINK_BOOTSTRAP', sys.platform, 'invocation_root_admitted=' + str(admitted))
        """, link, observed, artifact)
    print(output.splitlines()[-1])


@pytest.mark.parametrize("suffix", SUFFIXES)
def test_external_native_suffix_inventory_without_execution(tmp_path, suffix):
    _guard_child(tmp_path, """\
        suffix = sys.argv[4]
        artifact = external / ('trusted_fixture' + suffix)
        artifact.write_bytes(b'INERT - MUST NEVER EXECUTE')
        if suffix in machinery.EXTENSION_SUFFIXES or (
            sys.platform == 'win32' and suffix.lower() in machinery.EXTENSION_SUFFIXES
        ):
            spec = machinery.PathFinder.find_spec('trusted_fixture', [str(external)])
            assert Path(spec.origin) == artifact
            assert isinstance(spec.loader, machinery.ExtensionFileLoader)
        guard = NativeProvenance(repo)
        record = next(v for v in guard.inventory.values() if v['path'] == str(artifact))
        assert record['resolved_path'] == str(artifact.resolve())
        assert record['sha256'] == hashlib.sha256(artifact.read_bytes()).hexdigest()
        assert record['logical_origin'].endswith('/' + artifact.name)
        guard.verify()
        assert 'trusted_fixture' not in sys.modules
        """, tmp_path / "repo", tmp_path / "installed", suffix)


@pytest.mark.parametrize("change", ["content", "same_stat", "add", "remove", "replace"])
def test_external_native_inventory_detects_drift(tmp_path, change):
    _guard_child(tmp_path, """\
        artifact = external / ('trusted_fixture' + machinery.EXTENSION_SUFFIXES[0])
        artifact.write_bytes(b'inert-first')
        guard = NativeProvenance(repo)
        record = next(v for v in guard.inventory.values() if v['path'] == str(artifact))
        assert record['sha256'] == hashlib.sha256(b'inert-first').hexdigest()
        assert record['size'] == 11 and record['resolved_path'] == str(artifact.resolve())
        before = artifact.stat()
        change = sys.argv[4]
        if change in {'content', 'same_stat'}:
            artifact.write_bytes(b'inert-other')
            if change == 'same_stat':
                os.utime(artifact, ns=(before.st_atime_ns, before.st_mtime_ns))
                assert artifact.stat().st_size == before.st_size
                assert artifact.stat().st_mtime_ns == before.st_mtime_ns
        elif change == 'add':
            (external / ('new_fixture' + machinery.EXTENSION_SUFFIXES[0])).write_bytes(b'inert')
        elif change == 'remove':
            artifact.unlink()
        else:
            replacement = external / 'replacement'
            replacement.write_bytes(b'inert-other')
            os.replace(replacement, artifact)
        try:
            guard.verify()
        except RuntimeError as exc:
            assert 'changed' in str(exc)
        else:
            raise AssertionError('Native drift was accepted: ' + change)
        assert 'trusted_fixture' not in sys.modules
        """, tmp_path / "repo", tmp_path / "installed", change)


def test_same_named_artifacts_have_distinct_content_identity(tmp_path):
    _guard_child(tmp_path, """\
        first = external / 'one'; first.mkdir()
        second = external / 'two'; second.mkdir()
        name = 'fixture' + machinery.EXTENSION_SUFFIXES[0]
        (first / name).write_bytes(b'first')
        (second / name).write_bytes(b'other')
        guard = NativeProvenance(repo)
        records = [v for v in guard.inventory.values() if v['path'].startswith(str(external))]
        assert len(records) == 2
        assert len({v['logical_origin'] for v in records}) == 2
        assert len({v['sha256'] for v in records}) == 2
        guard.verify()
        """, tmp_path / "repo", tmp_path / "installed")


@pytest.mark.parametrize("kind", ["file", "directory"])
def test_native_symlink_identity_and_retargeting(tmp_path, kind):
    # Windows may require Developer Mode or link privilege; report genuine skip.
    probe = tmp_path / "probe"
    try:
        probe.symlink_to(tmp_path, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation unavailable on this host")
    probe.unlink()
    _guard_child(tmp_path, """\
        outside = external.parent / 'targets'; outside.mkdir()
        first = outside / 'first'; first.mkdir()
        second = outside / 'second'; second.mkdir()
        name = 'fixture' + machinery.EXTENSION_SUFFIXES[0]
        (first / name).write_bytes(b'first')
        (second / name).write_bytes(b'other')
        directory = sys.argv[4] == 'directory'
        link = external / ('package' if directory else name)
        link.symlink_to(first if directory else first / name, target_is_directory=directory)
        guard = NativeProvenance(repo)
        record = next(v for v in guard.inventory.values() if v['path'].startswith(str(external)))
        assert record['resolved_path'] == str((first / name).resolve())
        guard.verify()
        link.unlink()
        link.symlink_to(second if directory else second / name, target_is_directory=directory)
        try:
            guard.verify()
        except RuntimeError as exc:
            assert 'changed' in str(exc)
        else:
            raise AssertionError('Symlink retargeting was accepted')
        """, tmp_path / "repo", tmp_path / "installed", kind)


def test_checkout_symlink_to_external_native_is_rejected(tmp_path):
    artifact = tmp_path / "outside.so"
    artifact.write_bytes(b"inert")
    repo = tmp_path / "repo"
    repo.mkdir()
    try:
        (repo / "fixture.so").symlink_to(artifact)
    except OSError:
        pytest.skip("symlink creation unavailable on this host")
    _child(tmp_path, """\
        from scripts.benchmark_native_provenance import reject_checkout_native
        try:
            reject_checkout_native(Path(sys.argv[2]))
        except RuntimeError as exc:
            assert 'native' in str(exc)
        else:
            raise AssertionError('Checkout alias was accepted')
        """, repo)


@pytest.mark.parametrize("method", ["import", "explicit_loader", "nonstandard_suffix"])
def test_new_native_input_is_blocked_before_binary_execution(tmp_path, method):
    _guard_child(tmp_path, """\
        guard = NativeProvenance(repo)
        guard.install()
        name = 'unknown_fixture'
        suffix = '.bin' if sys.argv[4] == 'nonstandard_suffix' else machinery.EXTENSION_SUFFIXES[0]
        artifact = external / (name + suffix)
        artifact.write_bytes(b'inert-invalid-binary')
        try:
            if sys.argv[4] == 'import':
                importlib.import_module(name)
            else:
                # Same loader route used by the installed sibling's rust/target fallback.
                loader = machinery.ExtensionFileLoader(name, str(artifact))
                spec = importlib.util.spec_from_file_location(name, artifact, loader=loader)
                importlib.util.module_from_spec(spec)
        except NativeInputError as exc:
            assert 'before import' in str(exc)
            assert not isinstance(exc, Exception)
        else:
            raise AssertionError('Unknown extension reached the binary loader')
        assert name not in sys.modules
        assert artifact.read_bytes() == b'inert-invalid-binary'
        """, tmp_path / "repo", tmp_path / "installed", method)


@pytest.mark.parametrize("mismatch", ["file", "spec", "search", "removed"])
def test_loaded_native_origin_must_agree(tmp_path, mismatch):
    _guard_child(tmp_path, """\
        # Use the trusted installed NumPy extension in a fresh process.
        assert '_testcapi' not in sys.modules
        name = 'numpy._core._multiarray_umath'
        sys.modules.pop(name, None)
        guard = NativeProvenance(repo)
        guard.install()
        module = importlib.import_module(name)
        assert module.add([1, 2], [3, 4]).tolist() == [4, 6]
        guard.verify()
        mismatch = sys.argv[4]
        if mismatch == 'file':
            module.__file__ = str(external / 'absent.so')
        elif mismatch == 'spec':
            module.__spec__.origin = str(external / 'absent.so')
        elif mismatch == 'search':
            sys.path.reverse()
        else:
            del sys.modules[name]
        try:
            guard.verify()
        except (RuntimeError, FileNotFoundError):
            pass
        else:
            raise AssertionError('Loaded native origin mismatch accepted')
        """, tmp_path / "repo", tmp_path / "installed", mismatch)


def test_trusted_native_execution_is_recorded_without_claiming_application_use(tmp_path):
    _guard_child(tmp_path, """\
        sys.modules.pop('numpy._core._multiarray_umath', None)
        guard = NativeProvenance(repo)
        guard.install()
        native = importlib.import_module('numpy._core._multiarray_umath')
        assert isinstance(native.__loader__, machinery.ExtensionFileLoader)
        assert native.add([1, 2], [3, 4]).tolist() == [4, 6]
        receipt = guard.verify()
        assert receipt['observed_native_imports']['numpy._core._multiarray_umath'] == str(Path(native.__file__).resolve())
        record = receipt['artifacts'][receipt['loaded_extensions']['numpy._core._multiarray_umath']['artifact']]
        assert record['sha256'] == hashlib.sha256(Path(native.__file__).read_bytes()).hexdigest()
        assert receipt['computational_use'] == 'not inferred from availability or import'
        print('TRUSTED_NATIVE_NUMPY_EXECUTION', sys.platform, record['sha256'])
        """, tmp_path / "repo", tmp_path / "installed")


def test_clean_fallback_and_harmless_ignored_outputs(tmp_path):
    _guard_child(tmp_path, """\
        import subprocess
        def git(*args):
            return subprocess.check_output(['git', *args], cwd=repo, text=True)
        git('init', '--quiet')
        (repo / '.gitignore').write_text('outputs/\\n__pycache__/\\n*.log\\n')
        git('add', '.gitignore')
        git('-c', 'user.name=Test', '-c', 'user.email=test@example.invalid',
            'commit', '--quiet', '-m', 'fixture')
        sys.path.insert(0, str(repo))
        guard = NativeProvenance(repo)
        assert all(value is None for value in guard.resolutions.values())
        (repo / 'outputs').mkdir()
        (repo / 'outputs' / 'result.json').write_text('{}')
        (repo / '__pycache__').mkdir()
        # Tagged source caches are not sourceless import targets. Legacy fixture.pyc
        # would be importable as __pycache__.fixture and has its own negative case.
        (repo / '__pycache__' / ('fixture.' + sys.implementation.cache_tag + '.pyc')).write_bytes(b'cache')
        (repo / 'run.log').write_text('harmless output')
        assert git('status', '--porcelain') == ''
        guard.verify()
        """, tmp_path / "repo", tmp_path / "installed")


def test_compare_preserves_previous_receipt_directory(tmp_path):
    _child(tmp_path, """\
        from argparse import Namespace
        from scripts.benchmark_csv_pipeline import _compare
        output = Path(sys.argv[2]); output.mkdir()
        previous = output / 'summary.json'; previous.write_text('previous-valid')
        try:
            _compare(Namespace(output=str(output)))
        except FileExistsError:
            pass
        else:
            raise AssertionError('Existing benchmark evidence was overwritten')
        assert previous.read_text() == 'previous-valid'
        """, tmp_path / "output")


def test_installed_bridge_package_is_identified_without_execution(tmp_path):
    _guard_child(tmp_path, """\
        name = '_metroliza_group_stats_native'
        package = external / name; package.mkdir()
        source = package / '__init__.py'
        source.write_text('raise AssertionError("must not import to identify")')
        (package / (name + machinery.EXTENSION_SUFFIXES[0])).write_bytes(b'inert')
        guard = NativeProvenance(repo)
        assert guard.resolutions[name]['loader'] == 'SourceFileLoader'
        assert guard.resolutions[name]['sha256'] == hashlib.sha256(source.read_bytes()).hexdigest()
        assert name not in sys.modules
        guard.verify()
        source.write_text('raise AssertionError("different implementation")')
        try:
            guard.verify()
        except RuntimeError as exc:
            assert 'resolution changed' in str(exc)
        else:
            raise AssertionError('Native package wrapper drift accepted')
        """, tmp_path / "repo", tmp_path / "installed")


def test_installed_metroliza_native_execution(tmp_path):
    output = _guard_child(tmp_path, """\
        name = '_metroliza_group_stats_native'
        if machinery.PathFinder.find_spec(name, sys.path) is None:
            print('NATIVE_WHEEL_UNAVAILABLE')
            raise SystemExit(0)
        guard = NativeProvenance(repo)
        guard.install()
        native = importlib.import_module(name)
        values = native.coerce_sequence_to_float64([1, '2.5', 'bad'])
        assert values.shape == (3,) and values[0] == 1 and values[1] == 2.5
        assert str(values[2]) == 'nan'
        receipt = guard.verify()
        extensions = {k: v for k, v in receipt['loaded_extensions'].items() if name in k}
        assert extensions, 'Kernel executed without an identified native extension'
        for extension, record in extensions.items():
            artifact = receipt['artifacts'][record['artifact']]
            assert artifact['sha256'] == hashlib.sha256(Path(record['origin']).read_bytes()).hexdigest()
            print('TRUSTED_METROLIZA_NATIVE_EXECUTION', extension, artifact['sha256'])
        """, tmp_path / "repo", tmp_path / "installed")
    if "NATIVE_WHEEL_UNAVAILABLE" in output:
        pytest.skip("trusted repository native wheel not installed in this environment")
    assert "TRUSTED_METROLIZA_NATIVE_EXECUTION" in output
    print(output)


def _worker_fixture(tmp_path):
    tooling = tmp_path / "tooling"
    (tooling / "scripts").mkdir(parents=True)
    for name in ("benchmark_csv_pipeline.py", "benchmark_native_provenance.py"):
        (tooling / "scripts" / name).write_bytes((ROOT / "scripts" / name).read_bytes())
    (tooling / "scripts/__init__.py").write_text("")
    (tooling / ".gitignore").write_text("*.so\n*.pyd\n__pycache__/\n")
    repo = tmp_path / "repo"
    files = {
        ".gitignore": "*.so\n*.pyd\n__pycache__/\n",
        "scripts/benchmark_paths.py": (
            "def _install_headless_stubs(): pass\n"
            "def _create_csv_fixture(path, **kwargs): path.write_text('PART,DIM_01\\nA,1\\n')\n"
        ),
        "src/metroliza/__init__.py": "",
        "src/metroliza/industrial/__init__.py": "",
        "src/metroliza/industrial/industrial_analytics_state.py": (
            "class ProductionChartSelection:\n"
            "    def __init__(self, **kwargs): pass\n"
            "class ProductionMetricSelection: pass\n"
        ),
        "src/metroliza/industrial/industrial_analytics_workflow.py": (
            "from pathlib import Path\nimport os\nfrom dataclasses import dataclass\n"
            "MARKER = 'source'\n"
            "@dataclass\nclass Outcome:\n"
            "    html_dashboard_path: str = 'dashboard.html'\n"
            "    html_dashboard_assets_path: str = 'assets'\n"
            "    workbook_path: str = 'workbook.xlsx'\n"
            "    implementation_marker: str = MARKER\n"
            "def run_tabular_file_analytics(**kwargs):\n"
            "    Path(os.environ['PROVENANCE_TEST_MUTATION']).write_bytes(b'changed')\n"
            "    return Outcome()\n"
        ),
    }
    for relative, content in files.items():
        target = repo / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    (tooling / "scripts/benchmark_paths.py").write_text(files["scripts/benchmark_paths.py"])
    for checkout in (repo, tooling):
        subprocess.run(["git", "init", "--quiet", str(checkout)], check=True)
        subprocess.run(["git", "add", "."], cwd=checkout, check=True)
        subprocess.run(["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                        "commit", "--quiet", "-m", "synthetic workflow"], cwd=checkout, check=True)
    return tooling, repo


@pytest.mark.skipif(sys.platform != "linux", reason="Linux RSS worker; portable guard tested separately")
@pytest.mark.parametrize("change", ["native", "source", "helper", "driver", "shared_harness",
                                  "shared_dirty", "shared_native", "none"])
def test_worker_drift_never_publishes_a_success_receipt(tmp_path, change):
    """A real Git checkout and isolated synthetic workflow exercise worker ordering."""
    tooling, repo = _worker_fixture(tmp_path)
    target = {
        "native": repo / ("_metroliza_group_stats_native" + importlib.machinery.EXTENSION_SUFFIXES[0]),
        "source": repo / "src/metroliza/industrial/industrial_analytics_state.py",
        "helper": tooling / "scripts/benchmark_native_provenance.py",
        "driver": tooling / "scripts/benchmark_csv_pipeline.py",
        "shared_harness": tooling / "scripts/benchmark_paths.py",
        "shared_dirty": tooling / "scripts/benchmark_paths.py",
        "shared_native": tooling / "ignored_build.so",
        "none": tmp_path / "harmless.txt",
    }[change]
    if change == "shared_dirty":
        target.write_text(target.read_text() + "\n# Uncommitted shared harness change\n")
    elif change == "shared_native":
        target.write_bytes(b"inert - must not execute")
    output = _child(tmp_path, """\
        import os
        from argparse import Namespace
        sys.path[0] = sys.argv[2]
        os.environ['PROVENANCE_TEST_MUTATION'] = sys.argv[4]
        output = Path(sys.argv[5])
        try:
            from scripts import benchmark_csv_pipeline as driver
            # The isolated harness explicitly owns activation; ordinary imports
            # must not mutate an existing interpreter's bytecode settings.
            driver._start_bytecode_policy([sys.argv[2], sys.argv[3]])
            driver._worker(Namespace(repo=sys.argv[3], output=str(output),
                                     case='small', requests=2, profile=False))
        except RuntimeError as exc:
            assert sys.argv[6] != 'none', str(exc)
            assert any(word in str(exc) for word in ('native', 'changed', 'clean')), str(exc)
            print('WORKER_DRIFT_REJECTED', str(exc))
        else:
            assert sys.argv[6] == 'none', 'Worker published success after input drift'
            import json
            receipt = json.loads((output / 'result.json').read_text())
            assert len(receipt['native_modules']) == 5
            assert receipt['shared_tooling_root'] == str(Path(sys.argv[2]).resolve())
            assert receipt['harness_origin']['root'] == 'shared_tooling'
            assert receipt['shared_tooling_head'] != receipt['head']
            print('WORKER_VALID_ROOTS_ACCEPTED')
        if sys.argv[6] != 'none':
            assert not (output / 'result.json').exists()
        """, tooling, repo, (tmp_path / "harmless-native-test.txt" if change == "shared_native" else target),
        tmp_path / "output", change)
    assert ("WORKER_VALID_ROOTS_ACCEPTED" if change == "none" else "WORKER_DRIFT_REJECTED") in output
    if change not in {"shared_dirty", "shared_native"}:
        assert target.read_bytes() == b"changed", "Workflow must actually reach the injected mutation"


@pytest.mark.parametrize("changed_key", [
    "head", "driver_sha256", "native_helper_sha256", "shared_tooling_head", "native",
    "loaded_bridges", "loaded_extensions", "observed_native_imports", "initially_loaded",
    "bytecode_policy", "bytecode_unverified", "bytecode_reuse", "none", "guard_timings",
    "controller_prefix", "controller_writes", "controller_reuse", "controller_summary",
])
def test_compare_rejects_different_implementations_between_samples(tmp_path, changed_key):
    _child(tmp_path, """\
        from argparse import Namespace
        import json
        from scripts import benchmark_csv_pipeline as driver
        from scripts import benchmark_native_provenance as helper
        repo = Path(sys.argv[2]); repo.mkdir()
        # Localized worker receipt hook: this proves publication rejection, not execution.
        driver._checkout_identity = lambda repo: ('head', 'tree')
        driver._verify_checkout_identity = lambda *args: None
        driver._start_bytecode_policy([repo])
        if sys.argv[3] == 'controller_summary':
            original_summary = driver._summary
            def changed_summary(values):
                sys.dont_write_bytecode = False
                return original_summary(values)
            driver._summary = changed_summary
        def fake_worker(command, **kwargs):
            destination = Path(command[command.index('--output') + 1]); destination.mkdir()
            payload = {
                'head': 'head', 'tree': 'tree',
                'shared_tooling_head': 'head', 'shared_tooling_tree': 'tree',
                'driver_sha256': driver._sha(Path(driver.__file__)),
                'native_helper_sha256': driver._sha(Path(helper.__file__)),
                'bytecode_provenance': {
                    'policy': dict(driver._BYTECODE_POLICY), 'verified': True,
                    'prefix': str(destination / 'unique-child-prefix'),
                },
                'native_provenance': {
                    'artifacts': {'fixture': 'first'}, 'bridge_resolution': {},
                    'interpreter': {}, 'requested_backend_environment': {},
                    'loaded_bridges': {'_metroliza_group_stats_native': None},
                    'loaded_extensions': {}, 'observed_native_imports': {},
                    'initially_loaded': [], 'verification_s': 0.1, 'import_guard_s': 0.01,
                },
                'records': [{'workflow_s': 1, 'peak_rss_kib': 1}],
            }
            if '-1-' in destination.name:
                key = sys.argv[3]
                if key == 'native':
                    payload['native_provenance']['artifacts']['fixture'] = 'changed'
                elif key in ('loaded_bridges', 'loaded_extensions', 'observed_native_imports'):
                    # Availability/resolution remain fixed while observed loading differs.
                    payload['native_provenance'][key]['_metroliza_group_stats_native'] = 'known-origin'
                elif key == 'initially_loaded':
                    payload['native_provenance'][key].append('known-native-module')
                elif key == 'guard_timings':
                    payload['native_provenance'].update(verification_s=0.2, import_guard_s=0.02)
                elif key == 'bytecode_policy':
                    payload['bytecode_provenance']['policy']['cache_writes'] = True
                elif key == 'bytecode_unverified':
                    payload['bytecode_provenance']['verified'] = False
                elif key == 'bytecode_reuse':
                    payload['bytecode_provenance']['prefix'] = str(
                        destination.with_name(destination.name.replace('-1-', '-0-')) / 'unique-child-prefix')
                elif key == 'controller_reuse':
                    payload['bytecode_provenance']['prefix'] = driver._BYTECODE_STATE['prefix']
                elif key == 'controller_prefix':
                    sys.pycache_prefix = 'changed-prefix'
                elif key == 'controller_writes':
                    sys.dont_write_bytecode = False
                elif key == 'controller_summary':
                    pass
                elif key == 'none':
                    pass
                else:
                    payload[key] = 'changed'
            (destination / 'result.json').write_text(json.dumps(payload))
        driver.subprocess.run = fake_worker
        output = repo / 'output'
        try:
            driver._compare(Namespace(output=str(output), compare=['B=' + str(repo)],
                                     blocks=1, samples=1, requests=1, profile=False,
                                     case='small', timeout=30))
        except RuntimeError as exc:
            assert sys.argv[3] not in ('none', 'guard_timings'), str(exc)
            assert 'between samples' in str(exc) or (
                sys.argv[3].startswith('controller_') and 'bytecode' in str(exc))
        else:
            assert sys.argv[3] in ('none', 'guard_timings'), 'Mixed implementation evidence was summarized'
        assert (output / 'summary.json').exists() == (sys.argv[3] in ('none', 'guard_timings'))
        """, tmp_path / "repo", changed_key)


def test_native_alias_uses_verified_canonical_import_resolution(tmp_path):
    _guard_child(tmp_path, """\
        guard = NativeProvenance(repo)
        guard.install()
        # SciPy/Cython installs _cyutility as an alias of scipy._cyutility.
        import scipy.special
        native = sys.modules['scipy._cyutility']
        assert sys.modules['_cyutility'] is native
        receipt = guard.verify()
        canonical = receipt['loaded_extensions']['scipy._cyutility']
        alias = receipt['loaded_extensions']['_cyutility']
        assert alias == canonical
        assert alias['resolution_name'] == native.__spec__.name
        assert receipt['artifacts'][alias['artifact']]['sha256'] == hashlib.sha256(
            Path(native.__file__).read_bytes()).hexdigest()
        """, tmp_path / "repo", tmp_path / "installed")


@pytest.mark.parametrize('change', ['none', 'alias', 'attribute', 'origin', 'provider',
                                   'unrelated', 'loader', 'resolution'])
def test_native_exported_modules_are_bound_to_verified_provider(tmp_path, change):
    _guard_child(tmp_path, """\
        from importlib.machinery import ModuleSpec
        from types import ModuleType
        guard = NativeProvenance(repo)
        guard.install()
        import scipy.optimize
        provider_name = 'scipy.optimize._highspy._core'
        provider = sys.modules[provider_name]
        exports = {key: sys.modules[provider_name + '.' + key] for key in ('cb', 'simplex_constants')}
        for key, module in exports.items():
            assert vars(provider)[key] is module
            assert Path(module.__file__).resolve() == Path(provider.__file__).resolve()
        receipt = guard.verify()
        for key in exports:
            record = receipt['loaded_extensions'][provider_name + '.' + key]
            assert record['kind'] == 'native_export'
            assert record['provider'] == provider_name
            assert record['artifact'] == receipt['loaded_extensions'][provider_name]['artifact']
        change = sys.argv[4]
        if change == 'none':
            raise SystemExit(0)
        exported = exports['cb']
        if change == 'alias':
            sys.modules['synthetic_export_alias'] = exported
            receipt = guard.verify()
            assert receipt['loaded_extensions']['synthetic_export_alias'] == receipt['loaded_extensions'][exported.__name__]
            raise SystemExit(0)
        if change == 'attribute':
            del provider.cb
        elif change == 'origin':
            exported.__file__ = str(external / 'absent.so')
        elif change == 'provider':
            del sys.modules[provider_name]
        elif change == 'unrelated':
            extra = ModuleType('unrelated_export')
            extra.__file__ = provider.__file__
            sys.modules[extra.__name__] = extra
        elif change == 'loader':
            exported.__spec__ = ModuleSpec(exported.__name__, object(), origin=exported.__file__)
        else:
            provider.__spec__.origin = str(external / 'absent.so')
        try:
            guard.verify()
        except (RuntimeError, FileNotFoundError):
            pass
        else:
            raise AssertionError('Unproven native export relationship accepted: ' + change)
        """, tmp_path / "repo", tmp_path / "installed", change)


def _commit_bytecode_fixture(repo):
    subprocess.run(['git', 'init', '--quiet', str(repo)], check=True)
    subprocess.run(['git', 'add', '.'], cwd=repo, check=True)
    subprocess.run(['git', '-c', 'user.name=Regression', '-c',
                    'user.email=regression@example.invalid', 'commit', '--quiet',
                    '-m', 'trusted source fixture'], cwd=repo, check=True)


def _compile_stale_fixture(source, mode, *, stale=True, cache=None):
    fresh = source.read_bytes()
    cached = fresh.replace(b"MARKER = 'source'", b"MARKER = 'cached'") if stale else fresh
    assert len(fresh) == len(cached)
    source.write_bytes(cached)
    os.utime(source, (1700000000, 1700000000))
    cache = cache or source.parent / '__pycache__' / (source.stem + '.' + sys.implementation.cache_tag + '.pyc')
    py_compile.compile(str(source), cfile=str(cache), doraise=True,
                       invalidation_mode=getattr(py_compile.PycInvalidationMode, mode))
    source.write_bytes(fresh)
    os.utime(source, (1700000000, 1700000000))
    if mode == 'TIMESTAMP':
        header = cache.read_bytes()[:16]
        assert int.from_bytes(header[8:12], 'little') == int(source.stat().st_mtime)
        assert int.from_bytes(header[12:16], 'little') == source.stat().st_size
    return cache


def _source_entry_bytecode_case(tmp_path, location, mode, role='payload', *, stale=True,
                                inherited=False, cache_symlink=False, crlf=False):
    tooling, repo = tmp_path / 'tooling', tmp_path / 'repo'
    (tooling / 'scripts').mkdir(parents=True)
    repo.mkdir()
    (tooling / 'scripts/__init__.py').write_text('')
    helper = tooling / 'scripts/benchmark_native_provenance.py'
    helper.write_bytes((ROOT / 'scripts/benchmark_native_provenance.py').read_bytes())
    # The direct source-file bootstrap is real; only final CLI dispatch is a
    # localized probe. Importing a driver into an existing interpreter is not trust.
    driver_source = (ROOT / 'scripts/benchmark_csv_pipeline.py').read_text()
    driver_source = driver_source.rsplit('\nif __name__ == "__main__":', 1)[0]
    probe = '''
import importlib.machinery as _probe_machinery
import importlib as _probe_importlib
_probe_repo = Path(os.environ['BYTECODE_TEST_REPO'])
_probe_directory = Path(os.environ['BYTECODE_TEST_DIRECTORY'])
_probe_name = os.environ['BYTECODE_TEST_MODULE']
_probe_identity = _checkout_identity(_probe_repo)
sys.path.insert(0, str(_probe_directory))
_probe_spec = _probe_machinery.PathFinder.find_spec(_probe_name, [str(_probe_directory)])
assert isinstance(_probe_spec.loader, _probe_machinery.SourceFileLoader)
_probe_module = _probe_importlib.import_module(_probe_name)
assert _probe_module.MARKER == 'source', 'STALE_BYTECODE_EXECUTED: ' + _probe_module.MARKER
Path(os.environ['BYTECODE_TEST_RECEIPT']).write_text(json.dumps(_bytecode_receipt()))
print('SOURCE_ENTRY_BYTECODE_BYPASSED', _probe_identity)
'''
    driver = tooling / 'scripts/benchmark_csv_pipeline.py'
    driver.write_text(driver_source + probe)
    for checkout in (tooling, repo):
        (checkout / '.gitignore').write_text('__pycache__\n')
    directory = repo / location
    directory.mkdir(exist_ok=True)
    if role == 'payload':
        source, name = directory / 'provenance_fixture.py', 'provenance_fixture'
        source.write_text("MARKER = 'source'\n")
    elif role == 'package':
        directory.joinpath('fixture_package').mkdir()
        source, name = directory / 'fixture_package/__init__.py', 'fixture_package'
        source.write_text("MARKER = 'source'\n")
    elif role == 'helper':
        source, name, directory = helper, 'scripts.benchmark_native_provenance', tooling / 'scripts'
        source.write_text(source.read_text() + "\nMARKER = 'source'\n")
    else:
        source, name, directory = tooling / 'scripts/argparse.py', 'argparse', tooling / 'scripts'
        source.write_text("MARKER = 'source'\n")
    if crlf:
        source.write_bytes(source.read_bytes().replace(b'\r\n', b'\n').replace(b'\n', b'\r\n'))
    for checkout in (tooling, repo):
        # This fixture proves exact blob/source/cache bytes, including on Windows.
        # Keep Git's host text conversion from changing its synthetic source blobs.
        (checkout / '.gitattributes').write_text('* -text\n')
        _commit_bytecode_fixture(checkout)
    cache = None
    inherited_prefix = tmp_path / 'inherited-cache'
    if inherited:
        previous = sys.pycache_prefix
        try:
            sys.pycache_prefix = str(inherited_prefix)
            cache = Path(importlib.util.cache_from_source(str(source)))
        finally:
            sys.pycache_prefix = previous
    cache = _compile_stale_fixture(source, mode, stale=stale, cache=cache)
    cached_bytes = cache.read_bytes()
    if cache_symlink:
        target = tmp_path / 'user-cache'
        cache.parent.rename(target)
        _symlink_or_skip(cache.parent, target, directory=True)
    owner = tooling if source.is_relative_to(tooling) else repo
    assert subprocess.check_output(['git', 'status', '--porcelain'], cwd=owner) == b''
    if not inherited:
        ignored_entry = cache.parent if cache_symlink else cache
        assert subprocess.check_output(['git', 'check-ignore', str(ignored_entry)], cwd=owner)
    assert subprocess.check_output(['git', 'show', 'HEAD:' + source.relative_to(owner).as_posix()],
                                   cwd=owner) == source.read_bytes()
    receipt = tmp_path / 'receipt.json'
    env = dict(os.environ, BYTECODE_TEST_REPO=str(repo), BYTECODE_TEST_DIRECTORY=str(directory),
               BYTECODE_TEST_MODULE=name, BYTECODE_TEST_RECEIPT=str(receipt))
    if inherited:
        env['PYTHONPYCACHEPREFIX'] = str(inherited_prefix)
    result = subprocess.run([sys.executable, '-B', str(driver), '--repo', str(repo)],
                            cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert cache.read_bytes() == cached_bytes, 'Source-backed user cache must be preserved'
    assert 'SOURCE_ENTRY_BYTECODE_BYPASSED' in result.stdout
    policy = json.loads(receipt.read_text())
    assert not Path(policy['prefix']).parent.exists(), 'Owned empty reservation must be cleaned'
    assert not Path(policy['prefix']).is_relative_to(repo)
    assert not Path(policy['prefix']).is_relative_to(tooling)
    if inherited:
        assert not Path(policy['prefix']).is_relative_to(inherited_prefix)
    return receipt


@pytest.mark.parametrize('location', ['.', 'src'])
@pytest.mark.parametrize('mode', ['TIMESTAMP', 'UNCHECKED_HASH'])
def test_clean_checkout_must_not_execute_stale_ignored_bytecode(tmp_path, location, mode):
    """Promoted four Git/import fail-first cases, now through trusted source entry."""
    _source_entry_bytecode_case(tmp_path, location, mode)


@pytest.mark.parametrize('role', ['helper', 'argparse', 'package'])
@pytest.mark.parametrize('mode', ['TIMESTAMP', 'UNCHECKED_HASH'])
def test_bytecode_is_bypassed_before_bootstrap_helper_and_package_imports(tmp_path, role, mode):
    _source_entry_bytecode_case(tmp_path, 'src', mode, role)


def test_current_source_backed_cache_is_preserved(tmp_path):
    _source_entry_bytecode_case(tmp_path, '.', 'TIMESTAMP', stale=False)


@pytest.mark.parametrize('mode', ['TIMESTAMP', 'UNCHECKED_HASH'])
def test_inherited_populated_bytecode_prefix_is_bypassed_and_preserved(tmp_path, mode):
    _source_entry_bytecode_case(tmp_path, 'src', mode, inherited=True)


@pytest.mark.parametrize('mode', ['TIMESTAMP', 'UNCHECKED_HASH'])
def test_stale_tagged_bytecode_directory_symlink_is_bypassed_and_preserved(tmp_path, mode):
    _source_entry_bytecode_case(tmp_path, 'src', mode, cache_symlink=True)


@pytest.mark.parametrize('mode', ['TIMESTAMP', 'UNCHECKED_HASH'])
def test_crlf_source_bytecode_proof_preserves_exact_git_bytes(tmp_path, monkeypatch, mode):
    # Exercise Windows Git text conversion on every host, without persistent config.
    monkeypatch.setenv('GIT_CONFIG_COUNT', '1')
    monkeypatch.setenv('GIT_CONFIG_KEY_0', 'core.autocrlf')
    monkeypatch.setenv('GIT_CONFIG_VALUE_0', 'true')
    _source_entry_bytecode_case(tmp_path, 'src', mode, crlf=True)


@pytest.mark.parametrize('dont_write', [False, True])
def test_importing_provenance_helpers_preserves_caller_bytecode_policy(tmp_path, dont_write):
    _child(tmp_path, """\
        sys.pycache_prefix = str(Path(sys.argv[2]) / 'inherited-prefix')
        sys.dont_write_bytecode = sys.argv[3] == 'True'
        before = (sys.pycache_prefix, sys.dont_write_bytecode)
        from scripts import benchmark_csv_pipeline as driver
        from scripts import benchmark_native_provenance
        assert (sys.pycache_prefix, sys.dont_write_bytecode) == before
        assert driver._BYTECODE_STATE is None
        assert not any(name in sys.modules for name in ('numpy', 'pandas', 'matplotlib', 'resource'))
        """, tmp_path, dont_write)


@pytest.mark.parametrize('relative', ['fixture.pyc', 'src/fixture.pyc', 'pkg/__init__.pyc',
                                     '__pycache__/fixture.pyc', 'src/pkg/__init__.PYC'])
def test_importable_sourceless_bytecode_is_rejected_without_deletion(tmp_path, relative):
    repo = tmp_path / 'repo'
    repo.mkdir()
    (repo / '.gitignore').write_text('*.[pP][yY][cC]\n')
    _commit_bytecode_fixture(repo)
    source = tmp_path / 'trusted_fixture.py'
    source.write_text("MARKER = 'cached'\n")
    cache = repo / relative
    cache.parent.mkdir(parents=True, exist_ok=True)
    py_compile.compile(str(source), cfile=str(cache), doraise=True)
    before = cache.read_bytes()
    assert subprocess.check_output(['git', 'status', '--porcelain'], cwd=repo) == b''
    assert subprocess.check_output(['git', 'check-ignore', str(cache)], cwd=repo)
    _child(tmp_path, """\
        from scripts.benchmark_csv_pipeline import _checkout_identity
        import importlib.machinery as machinery
        repo, cache = Path(sys.argv[2]), Path(sys.argv[3])
        name = cache.stem if cache.stem != '__init__' else cache.parent.name
        search = cache.parent if cache.stem != '__init__' else cache.parent.parent
        if cache.suffix == '.pyc' or sys.platform == 'win32':
            spec = machinery.PathFinder.find_spec(name, [str(search)])
            assert isinstance(spec.loader, machinery.SourcelessFileLoader)
            assert Path(spec.origin) == cache
        try:
            _checkout_identity(repo)
        except RuntimeError as exc:
            assert 'sourceless bytecode' in str(exc)
        else:
            raise AssertionError('Importable sourceless bytecode attributed to clean source')
        """, repo, cache)
    assert cache.read_bytes() == before


@pytest.mark.parametrize('change', ['prefix', 'writes', 'populated', 'removed', 'policy', 'pid'])
def test_bytecode_policy_drift_fails_closed(tmp_path, change):
    _child(tmp_path, """\
        import os
        from scripts import benchmark_csv_pipeline as driver
        driver._start_bytecode_policy([sys.argv[2]])
        state = driver._BYTECODE_STATE
        if sys.argv[3] == 'prefix':
            sys.pycache_prefix = str(Path(sys.argv[2]) / 'different-prefix')
        elif sys.argv[3] == 'writes':
            sys.dont_write_bytecode = False
        elif sys.argv[3] == 'populated':
            Path(state['prefix']).mkdir()
            Path(state['prefix'], 'preserved.txt').write_text('unexpected data')
        elif sys.argv[3] == 'removed':
            os.rmdir(state['reservation'])
        elif sys.argv[3] == 'policy':
            driver._BYTECODE_POLICY['version'] += 1
        else:
            state['pid'] += 1
        try:
            driver._verify_bytecode_policy()
        except RuntimeError as exc:
            assert 'bytecode' in str(exc)
        else:
            raise AssertionError('Bytecode policy drift accepted')
        if sys.argv[3] == 'pid':
            state['pid'] = os.getpid()
        driver._close_bytecode_policy()
        if sys.argv[3] == 'populated':
            assert Path(state['prefix'], 'preserved.txt').read_text() == 'unexpected data'
        """, tmp_path / 'source', change)


def _symlink_or_skip(link, target, *, directory=False):
    try:
        link.symlink_to(target, target_is_directory=directory)
    except OSError as exc:
        pytest.skip('symlink creation unavailable on this host: ' + str(exc))


@pytest.mark.parametrize('kind', ['file', 'package', 'namespace', 'internal_file',
                                  'internal_package', 'data'])
def test_source_aliases_remain_bound_to_the_git_root(tmp_path, kind):
    repo, external = tmp_path / 'repo', tmp_path / 'external'
    repo.mkdir()
    external.mkdir()
    internal = kind.startswith('internal')
    target_root = repo if internal else external
    if kind.endswith('file'):
        target = target_root / 'tracked.py'
        target.write_text("MARKER = 'source'\n")
        alias = repo / 'alias.py'
        _symlink_or_skip(alias, target)
    else:
        target = target_root / 'payload'
        target.mkdir()
        source_name = 'data.txt' if kind == 'data' else (
            'child.py' if kind == 'namespace' else '__init__.py')
        (target / source_name).write_text("MARKER = 'source'\n")
        alias = repo / 'alias'
        _symlink_or_skip(alias, target, directory=True)
    _commit_bytecode_fixture(repo)
    assert subprocess.check_output(['git', 'status', '--porcelain'], cwd=repo) == b''
    _child(tmp_path, """\
        from scripts import benchmark_csv_pipeline as driver
        import importlib.machinery as machinery
        repo, kind = Path(sys.argv[2]), sys.argv[3]
        if kind != 'data':
            spec = machinery.PathFinder.find_spec('alias', [str(repo)])
            if kind == 'namespace':
                spec = machinery.PathFinder.find_spec('alias.child', list(spec.submodule_search_locations))
            assert isinstance(spec.loader, machinery.SourceFileLoader)
            assert Path(spec.origin).resolve().is_relative_to(repo) == kind.startswith('internal')
        for check in (driver._bootstrap_reject_native, driver._checkout_identity):
            try:
                check(repo)
            except RuntimeError as exc:
                assert not kind.startswith('internal') and kind != 'data', str(exc)
                assert 'source alias' in str(exc), str(exc)
            else:
                assert kind.startswith('internal') or kind == 'data', 'External source alias accepted'
        """, repo, kind)
    assert alias.exists(), 'No user alias or target may be deleted'


@pytest.mark.skipif(sys.platform != 'linux', reason='Linux RSS worker; portable source-entry probes run separately')
@pytest.mark.parametrize('mode', ['TIMESTAMP', 'UNCHECKED_HASH'])
def test_measured_worker_executes_source_with_stale_ignored_bytecode(tmp_path, mode):
    tooling, repo = _worker_fixture(tmp_path)
    source = repo / 'src/metroliza/industrial/industrial_analytics_workflow.py'
    cache = _compile_stale_fixture(source, mode)
    before = cache.read_bytes()
    assert subprocess.check_output(['git', 'status', '--porcelain'], cwd=repo) == b''
    assert subprocess.check_output(['git', 'check-ignore', str(cache)], cwd=repo)
    output = tmp_path / 'output'
    mutation = tmp_path / 'workflow-ran'
    result = subprocess.run(
        [sys.executable, '-B', str(tooling / 'scripts/benchmark_csv_pipeline.py'),
         '--worker', '--repo', str(repo), '--case', 'small', '--requests', '2', '--output', str(output)],
        env=dict(os.environ, PROVENANCE_TEST_MUTATION=str(mutation), MPLBACKEND='Agg'),
        cwd=tmp_path, capture_output=True, text=True, timeout=90,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    receipt = json.loads((output / 'result.json').read_text())
    assert len(receipt['records']) == 2
    assert all(r['outcome']['implementation_marker'] == 'source' for r in receipt['records'])
    assert all(r['workflow_s'] > 0 for r in receipt['records'])
    assert receipt['head'] == subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo, text=True).strip()
    assert receipt['bytecode_provenance']['verified'] is True
    assert not Path(receipt['bytecode_provenance']['prefix']).parent.exists()
    assert receipt['driver_bootstrap_s'] > 0 and receipt['input_validation_s'] > 0
    assert mutation.read_bytes() == b'changed'
    assert cache.read_bytes() == before


@pytest.mark.parametrize('kind', ['file', 'package'])
def test_sourceless_bytecode_symlinks_rejected_at_bootstrap_and_checkout(tmp_path, kind):
    repo, external = tmp_path / 'repo', tmp_path / 'external'
    repo.mkdir()
    external.mkdir()
    source = tmp_path / 'trusted_fixture.py'
    source.write_text("MARKER = 'cached'\n")
    cache = external / ('fixture.pyc' if kind == 'file' else '__init__.pyc')
    py_compile.compile(str(source), cfile=str(cache), doraise=True)
    before = cache.read_bytes()
    alias = repo / ('fixture.pyc' if kind == 'file' else 'package')
    _symlink_or_skip(alias, cache if kind == 'file' else external, directory=kind == 'package')
    _commit_bytecode_fixture(repo)
    _child(tmp_path, """\
        from scripts import benchmark_csv_pipeline as driver
        for check in (driver._bootstrap_reject_native, driver._checkout_identity):
            try:
                check(Path(sys.argv[2]))
            except RuntimeError as exc:
                assert 'sourceless bytecode' in str(exc), str(exc)
            else:
                raise AssertionError('Sourceless alias accepted')
        """, repo)
    assert cache.read_bytes() == before and alias.exists()


@pytest.mark.parametrize('change', ['dangling_prefix', 'reservation_link', 'permissions', 'externality'])
def test_bytecode_prefix_filesystem_boundaries(tmp_path, change):
    if change == 'permissions' and os.name == 'nt':
        pytest.skip('POSIX mode check; Windows uses inherited user-temp ACLs')
    if change in ('dangling_prefix', 'reservation_link'):
        _symlink_or_skip(tmp_path / 'probe', tmp_path / 'absent', directory=True)
    _child(tmp_path, """\
        import os
        from scripts import benchmark_csv_pipeline as driver
        root = Path(sys.argv[2]); root.mkdir()
        driver._bytecode_temp_parents = lambda: [str(root)]
        before = (sys.pycache_prefix, sys.dont_write_bytecode)
        driver._start_bytecode_policy([root / 'source'])
        state = driver._BYTECODE_STATE
        reservation = Path(state['reservation'])
        prefix = Path(state['prefix'])
        change = sys.argv[3]
        roots = ()
        if change == 'dangling_prefix':
            prefix.symlink_to(root / 'absent', target_is_directory=True)
        elif change == 'reservation_link':
            reservation.rename(root / 'preserved-reservation')
            reservation.symlink_to(root / 'preserved-reservation', target_is_directory=True)
        elif change == 'permissions':
            reservation.chmod(0o755)
        else:
            roots = (root,)
        try:
            driver._verify_bytecode_policy(roots)
        except RuntimeError as exc:
            assert 'bytecode' in str(exc)
        else:
            raise AssertionError('Filesystem bytecode drift accepted')
        driver._close_bytecode_policy()
        assert (sys.pycache_prefix, sys.dont_write_bytecode) == before
        if change == 'dangling_prefix':
            assert prefix.is_symlink(), 'Unexpected cache contents must be retained'
        elif change == 'reservation_link':
            assert reservation.is_symlink() and (root / 'preserved-reservation').is_dir()
        """, tmp_path / 'temporary', change)


def test_bytecode_prefix_requires_writable_external_parent(tmp_path):
    _child(tmp_path, """\
        from scripts import benchmark_csv_pipeline as driver
        root = Path(sys.argv[2]); root.mkdir()
        driver._bytecode_temp_parents = lambda: [str(root)]
        before = (sys.pycache_prefix, sys.dont_write_bytecode)
        try:
            driver._start_bytecode_policy([root])
        except RuntimeError as exc:
            assert 'external temporary directory' in str(exc)
        else:
            raise AssertionError('Cache reservation inside verified source accepted')
        assert not list(root.iterdir())
        assert driver._BYTECODE_STATE is None
        assert (sys.pycache_prefix, sys.dont_write_bytecode) == before
        """, tmp_path / 'temporary')


def test_source_entry_uses_distinct_process_prefixes(tmp_path):
    receipts = [json.loads(_source_entry_bytecode_case(tmp_path / str(index), '.', 'TIMESTAMP').read_text())
                for index in range(2)]
    assert receipts[0]['policy'] == receipts[1]['policy']
    assert receipts[0]['prefix'] != receipts[1]['prefix']
    assert receipts[0]['pid'] != receipts[1]['pid']


@pytest.mark.parametrize('dont_write', [False, True])
def test_bytecode_policy_success_cleanup_restores_caller(tmp_path, dont_write):
    _child(tmp_path, """\
        from scripts import benchmark_csv_pipeline as driver
        sys.pycache_prefix = str(Path(sys.argv[2]) / 'caller-prefix')
        sys.dont_write_bytecode = sys.argv[3] == 'True'
        before = (sys.pycache_prefix, sys.dont_write_bytecode)
        driver._start_bytecode_policy([sys.argv[2]])
        reservation = Path(driver._BYTECODE_STATE['reservation'])
        driver._verify_bytecode_policy()
        driver._close_bytecode_policy()
        driver._close_bytecode_policy()
        assert not reservation.exists()
        assert (sys.pycache_prefix, sys.dont_write_bytecode) == before
        """, tmp_path / 'source', dont_write)


def test_module_entry_refuses_measurement_claim(tmp_path):
    result = subprocess.run([sys.executable, '-B', '-m', 'scripts.benchmark_csv_pipeline', '--help'],
                            cwd=ROOT, capture_output=True, text=True, timeout=30)
    assert result.returncode != 0
    assert 'Execute the reviewed driver source file directly' in result.stderr


@pytest.mark.skipif(sys.platform != 'linux', reason='Linux RSS worker; portable policy checks run separately')
@pytest.mark.parametrize('boundary', ['setup', 'request', 'receipt'])
@pytest.mark.parametrize('change', ['prefix', 'writes'])
def test_worker_policy_drift_rejected_at_evidence_boundaries(tmp_path, boundary, change):
    tooling, repo = _worker_fixture(tmp_path)
    mutation = tmp_path / 'drift-was-exercised'
    drift = (
        '\nimport sys\nimport os\nfrom pathlib import Path\n'
        'def _drift_policy():\n'
        "    Path(os.environ['PROVENANCE_TEST_MUTATION']).write_text('policy drift exercised')\n"
        + ("    sys.pycache_prefix = 'changed-prefix'\n" if change == 'prefix'
           else '    sys.dont_write_bytecode = False\n')
    )
    if boundary == 'request':
        source = repo / 'src/metroliza/industrial/industrial_analytics_workflow.py'
        source.write_text(source.read_text().replace('    return Outcome()',
                                                   '    _drift_policy()\n    return Outcome()') + drift)
        _commit_bytecode_fixture(repo)
    else:
        source = tooling / 'scripts/benchmark_paths.py'
        hook = (
            '\n_original_create = _create_csv_fixture\n'
            'def _create_csv_fixture(*args, **kwargs):\n'
            '    _original_create(*args, **kwargs)\n'
            '    _drift_policy()\n'
        ) if boundary == 'setup' else (
            '\ndef _install_headless_stubs():\n'
            "    driver = sys.modules['__main__']\n"
            '    original = driver.asdict\n'
            '    def after_request_check(value):\n'
            '        result = original(value)\n'
            '        _drift_policy()\n'
            '        return result\n'
            '    driver.asdict = after_request_check\n'
        )
        source.write_text(source.read_text() + drift + hook)
        _commit_bytecode_fixture(tooling)
    output = tmp_path / 'output'
    result = subprocess.run(
        [sys.executable, '-B', str(tooling / 'scripts/benchmark_csv_pipeline.py'),
         '--worker', '--repo', str(repo), '--case', 'small', '--requests', '1', '--output', str(output)],
        env=dict(os.environ, PROVENANCE_TEST_MUTATION=str(mutation), MPLBACKEND='Agg'),
        cwd=tmp_path, capture_output=True, text=True, timeout=90,
    )
    assert result.returncode != 0, 'Worker published success after policy drift'
    assert 'Benchmark bytecode policy or fresh prefix changed' in result.stderr
    assert mutation.read_text() == 'policy drift exercised'
    assert not (output / 'result.json').exists()


@pytest.mark.parametrize('kind', ['file', 'package'])
@pytest.mark.parametrize('target_tracked', [False, True])
def test_git_tracked_alias_requires_git_owned_source_target(tmp_path, kind, target_tracked):
    repo = tmp_path / 'repo'
    repo.mkdir()
    ignored = repo / 'ignored_payload'
    ignored.mkdir()
    (repo / '.gitignore').write_text('ignored_payload/\n')
    source = ignored / ('target.py' if kind == 'file' else '__init__.py')
    source.write_text("MARKER = 'source'\n")
    alias = repo / ('alias.py' if kind == 'file' else 'alias')
    _symlink_or_skip(alias, source if kind == 'file' else ignored, directory=kind == 'package')
    subprocess.run(['git', 'init', '--quiet', str(repo)], check=True)
    if target_tracked:
        subprocess.run(['git', 'add', '-f', str(source)], cwd=repo, check=True)
    _commit_bytecode_fixture(repo)
    assert subprocess.check_output(['git', 'status', '--porcelain'], cwd=repo) == b''
    _child(tmp_path, """\
        import importlib.machinery as machinery
        from scripts import benchmark_csv_pipeline as driver
        repo, tracked = Path(sys.argv[2]), sys.argv[3] == 'True'
        spec = machinery.PathFinder.find_spec('alias', [str(repo)])
        assert isinstance(spec.loader, machinery.SourceFileLoader)
        assert Path(spec.origin).resolve().is_relative_to(repo / 'ignored_payload')
        try:
            driver._checkout_identity(repo)
        except RuntimeError as exc:
            assert not tracked, str(exc)
            assert 'untracked source' in str(exc), str(exc)
        else:
            assert tracked, 'Git-clean symlink attributed ignored executable bytes to HEAD'
        """, repo, target_tracked)
    assert alias.exists() and source.read_text() == "MARKER = 'source'\n"


@pytest.mark.skipif(sys.platform != 'win32', reason='Native Windows directory-junction boundary')
@pytest.mark.parametrize('kind', ['package', 'data'])
def test_windows_junction_source_boundary(tmp_path, kind):
    repo, external = tmp_path / 'repo', tmp_path / 'external'
    repo.mkdir()
    external.mkdir()
    source = external / ('__init__.py' if kind == 'package' else 'data.txt')
    source.write_text("MARKER = 'source'\n")
    alias = repo / 'alias'
    result = subprocess.run(['cmd', '/c', 'mklink', '/J', str(alias), str(external)],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert alias.resolve() == external.resolve()
    _commit_bytecode_fixture(repo)
    _child(tmp_path, """\
        from scripts import benchmark_csv_pipeline as driver
        repo, kind = Path(sys.argv[2]), sys.argv[3]
        for check in (driver._bootstrap_reject_native, driver._checkout_identity):
            try:
                check(repo)
            except RuntimeError as exc:
                assert kind == 'package' and 'source alias' in str(exc), str(exc)
            else:
                assert kind == 'data', 'External junction source accepted'
        """, repo, kind)
    assert alias.exists() and source.read_text() == "MARKER = 'source'\n"


@pytest.mark.parametrize('kind', ['directory', 'symlink'])
def test_bytecode_reservation_collision_never_adopts_existing_contents(tmp_path, kind):
    if kind == 'symlink':
        _symlink_or_skip(tmp_path / 'probe', tmp_path / 'absent', directory=True)
    _child(tmp_path, """\
        from scripts import benchmark_csv_pipeline as driver
        root = Path(sys.argv[2]); root.mkdir()
        reservation = root / ('metroliza-bytecode-' + '00' * 24)
        target = root / 'preserved' if sys.argv[3] == 'symlink' else reservation
        target.mkdir()
        (target / 'data.txt').write_text('user data')
        if sys.argv[3] == 'symlink':
            reservation.symlink_to(target, target_is_directory=True)
        driver._bytecode_temp_parents = lambda: [str(root)]
        driver.os.urandom = lambda count: bytes(count)
        before = (sys.pycache_prefix, sys.dont_write_bytecode)
        try:
            driver._start_bytecode_policy([root / 'source'])
        except RuntimeError as exc:
            assert 'No writable external temporary directory' in str(exc)
        else:
            raise AssertionError('Existing reservation was adopted as fresh')
        assert driver._BYTECODE_STATE is None
        assert (sys.pycache_prefix, sys.dont_write_bytecode) == before
        assert (target / 'data.txt').read_text() == 'user data'
        assert not (target / 'unused-cache').exists()
        """, tmp_path / 'temporary', kind)


@pytest.mark.parametrize('entry', ['actual_cli', 'admitted_link_directory'])
def test_direct_driver_symlink_preserves_trusted_source_entry(tmp_path, entry):
    tooling = tmp_path / 'source' / 'scripts'
    tooling.mkdir(parents=True)
    driver = tooling / 'benchmark_csv_pipeline.py'
    driver.write_bytes((ROOT / 'scripts/benchmark_csv_pipeline.py').read_bytes())
    invocation = tmp_path / 'invocation'
    invocation.mkdir()
    link = invocation / 'entry.py'
    _symlink_or_skip(link, driver)
    if entry == 'actual_cli':
        result = subprocess.run([sys.executable, '-B', str(link), '--help'], cwd=tmp_path,
                                capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stdout + result.stderr
        assert '--worker' in result.stdout
    else:
        # Emulate the admitted directory on hosts whose CLI resolves it away;
        # native Windows also executes the actual-CLI case above.
        _child(tmp_path, """\
            link = Path(sys.argv[2])
            sys.path[0] = str(link.parent)
            sys.argv = [str(link), '--help']
            try:
                exec(compile(link.read_bytes(), str(link), 'exec'),
                     {'__file__': str(link), '__name__': '__main__',
                      '__package__': None, '__spec__': None})
            except SystemExit as exc:
                assert exc.code == 0
            else:
                raise AssertionError('Trusted driver entry symlink failed to show help')
            """, link)
    assert link.is_symlink() and driver.exists()
