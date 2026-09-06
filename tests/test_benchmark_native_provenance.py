"""Native attribution regressions use fresh interpreters; inert files never execute."""
from __future__ import annotations

import importlib.machinery
from pathlib import Path
import subprocess
import sys
from textwrap import dedent

import pytest

ROOT = Path(__file__).resolve().parents[1]
SUFFIXES = tuple(dict.fromkeys([*importlib.machinery.EXTENSION_SUFFIXES, ".so", ".pyd"]))


def _child(tmp_path, code, *args):
    result = subprocess.run(
        [sys.executable, "-I", "-c", "import sys\nfrom pathlib import Path\n"
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
        (repo / '.gitignore').write_text('*.so\\n*.pyd\\n')
        git('add', '.gitignore')
        git('-c', 'user.name=Test', '-c', 'user.email=test@example.invalid',
            'commit', '--quiet', '-m', 'inert fixture')
        directory = repo / location
        directory.mkdir(exist_ok=True)
        artifact = directory / ('_metroliza_group_stats_native' + suffix)
        artifact.write_bytes(b'INERT - MUST NEVER EXECUTE')
        assert git('status', '--porcelain') == ''
        assert git('check-ignore', str(artifact)).strip()
        if suffix in machinery.EXTENSION_SUFFIXES:
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
        (repo / '__pycache__' / 'fixture.pyc').write_bytes(b'cache')
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


@pytest.mark.skipif(sys.platform != "linux", reason="Linux RSS worker; portable guard tested separately")
@pytest.mark.parametrize("change", ["native", "source", "helper", "driver"])
def test_worker_drift_never_publishes_a_success_receipt(tmp_path, change):
    """A real Git checkout and isolated synthetic workflow exercise worker ordering."""
    tooling = tmp_path / "tooling"
    (tooling / "scripts").mkdir(parents=True)
    for name in ("benchmark_csv_pipeline.py", "benchmark_native_provenance.py"):
        (tooling / "scripts" / name).write_bytes((ROOT / "scripts" / name).read_bytes())
    repo = tmp_path / "repo"
    files = {
        ".gitignore": "*.so\n*.pyd\n",
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
            "from pathlib import Path\nimport os\n"
            "def run_tabular_file_analytics(**kwargs):\n"
            "    Path(os.environ['PROVENANCE_TEST_MUTATION']).write_bytes(b'changed')\n"
            "    return None\n"
        ),
    }
    for relative, content in files.items():
        target = repo / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    subprocess.run(["git", "init", "--quiet", str(repo)], check=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                    "commit", "--quiet", "-m", "synthetic workflow"], cwd=repo, check=True)
    target = {
        "native": repo / ("_metroliza_group_stats_native" + importlib.machinery.EXTENSION_SUFFIXES[0]),
        "source": repo / "src/metroliza/industrial/industrial_analytics_state.py",
        "helper": tooling / "scripts/benchmark_native_provenance.py",
        "driver": tooling / "scripts/benchmark_csv_pipeline.py",
    }[change]
    output = _child(tmp_path, """\
        import os
        from argparse import Namespace
        sys.path[0] = sys.argv[2]
        from scripts.benchmark_csv_pipeline import _worker
        os.environ['PROVENANCE_TEST_MUTATION'] = sys.argv[4]
        output = Path(sys.argv[5])
        try:
            _worker(Namespace(repo=sys.argv[3], output=str(output),
                              case='small', requests=2, profile=False))
        except RuntimeError as exc:
            assert any(word in str(exc) for word in ('native', 'changed', 'clean')), str(exc)
            print('WORKER_DRIFT_REJECTED', str(exc))
        else:
            raise AssertionError('Worker published success after input drift')
        assert not (output / 'result.json').exists()
        """, tooling, repo, target, tmp_path / "output")
    assert "WORKER_DRIFT_REJECTED" in output


@pytest.mark.parametrize("changed_key", ["head", "driver_sha256", "native_helper_sha256", "native"])
def test_compare_rejects_different_implementations_between_samples(tmp_path, changed_key):
    _child(tmp_path, """\
        from argparse import Namespace
        import json
        from scripts import benchmark_csv_pipeline as driver
        from scripts import benchmark_native_provenance as helper
        repo = Path(sys.argv[2]); repo.mkdir()
        # Localized worker receipt hook: this proves publication rejection, not execution.
        driver._checkout_identity = lambda repo: ('head', 'tree')
        def fake_worker(command, **kwargs):
            destination = Path(command[command.index('--output') + 1]); destination.mkdir()
            payload = {
                'head': 'head', 'tree': 'tree',
                'driver_sha256': driver._sha(Path(driver.__file__)),
                'native_helper_sha256': driver._sha(Path(helper.__file__)),
                'native_provenance': {
                    'artifacts': {'fixture': 'first'}, 'bridge_resolution': {},
                    'interpreter': {}, 'requested_backend_environment': {},
                },
                'records': [{'workflow_s': 1, 'peak_rss_kib': 1}],
            }
            if '-1-' in destination.name:
                key = sys.argv[3]
                if key == 'native':
                    payload['native_provenance']['artifacts']['fixture'] = 'changed'
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
            assert 'between samples' in str(exc)
        else:
            raise AssertionError('Mixed implementation evidence was summarized')
        assert not (output / 'summary.json').exists()
        """, tmp_path / "repo", changed_key)
