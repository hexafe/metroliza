"""Revision conflict, interrupted replacement, and hostile file controls."""
from dataclasses import replace
import json
import os
from uuid import uuid4

import pytest

from metroliza.recipes.builtin_recipes import REPORTS_EXCEL_MAIN, builtin_binding
from metroliza.recipes.contracts import MAX_PAYLOAD_BYTES, RecipeError
from metroliza.recipes.storage import RecipeStore, copy_recipe


def seed(tmp_path):
    store = RecipeStore(tmp_path / "private")
    item = copy_recipe(REPORTS_EXCEL_MAIN, builtin_binding(REPORTS_EXCEL_MAIN,
        str(tmp_path / "input"), str(tmp_path / "output.xlsx")), name="PRIVATE_NAME")
    saved = store.save(item.definition, item.binding, expected_revision=None)
    return store, saved


def test_roundtrip_and_conflict_preserve_newer_revision(tmp_path):
    store, first = seed(tmp_path)
    assert store.load(first.definition.recipe_id) == first
    second = store.save(first.definition, replace(first.binding, name="New"), expected_revision=1)
    assert second.binding.revision == 2
    with pytest.raises(RecipeError, match="revision_conflict"):
        store.save(first.definition, first.binding, expected_revision=1)
    assert store.load(first.definition.recipe_id) == second


def test_interrupted_replace_keeps_complete_previous_bytes(tmp_path, monkeypatch):
    store, first = seed(tmp_path)
    path = store.root / f"{first.definition.recipe_id}.json"
    previous = path.read_bytes()
    def fail_replace(*_args):
        raise OSError("synthetic interruption")
    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(OSError):
        store.save(first.definition, replace(first.binding, name="Changed"), expected_revision=1)
    assert path.read_bytes() == previous
    assert not tuple(store.root.glob("*.tmp"))


def test_builtin_read_only_and_private_directory(tmp_path):
    store = RecipeStore(tmp_path / "private")
    with pytest.raises(RecipeError, match="builtin_read_only"):
        store.save(REPORTS_EXCEL_MAIN, builtin_binding(REPORTS_EXCEL_MAIN), expected_revision=None)
    with pytest.raises(RecipeError, match="private_location_required"):
        RecipeStore(tmp_path / "input" / "recipes", forbidden_roots=(tmp_path / "input",))


@pytest.mark.parametrize("mutation", ["newer", "unknown", "duplicate", "oversize"])
def test_reject_invalid_payload_without_execution(tmp_path, mutation):
    store, saved = seed(tmp_path)
    path = store.root / f"{saved.definition.recipe_id}.json"
    payload = json.loads(path.read_text())
    if mutation == "newer":
        payload["definition"]["format_version"] = 900
    elif mutation == "unknown":
        payload["definition"]["steps"][0]["kind"] = "run_python"
    if mutation == "oversize":
        path.write_bytes(b" " * (MAX_PAYLOAD_BYTES + 1))
    elif mutation == "duplicate":
        path.write_text('{"definition":{},"definition":{},"binding":{}}')
    else:
        path.write_text(json.dumps(payload))
    with pytest.raises(RecipeError):
        store.load(saved.definition.recipe_id)


def test_symlink_recipe_not_followed(tmp_path):
    store, saved = seed(tmp_path)
    path = store.root / f"{saved.definition.recipe_id}.json"
    target = tmp_path / "private-other"
    path.rename(target)
    try:
        path.symlink_to(target)
    except OSError:
        pytest.skip("platform does not permit symlinks")
    with pytest.raises(RecipeError, match="unsafe_store"):
        store.load(saved.definition.recipe_id)


def test_private_store_cannot_live_inside_bound_input_folder(tmp_path):
    store = RecipeStore(tmp_path / "input" / "private")
    copied = copy_recipe(REPORTS_EXCEL_MAIN, builtin_binding(REPORTS_EXCEL_MAIN,
        str(tmp_path / "input"), str(tmp_path / "output.xlsx")), name="Private")
    with pytest.raises(RecipeError, match="private_location_required"):
        store.save(copied.definition, copied.binding, expected_revision=None)
    assert not store.root.exists()


def test_catalog_recovers_each_entry_independently_and_keeps_damaged_bytes(tmp_path):
    store, saved = seed(tmp_path)
    corrupt = store.root / f"{uuid4()}.json"
    newer = store.root / f"{uuid4()}.json"
    corrupt.write_bytes(b"broken recipe")
    newer.write_text(json.dumps({"definition": {"format_version": 900, "future_option": True}}))
    original = corrupt.read_bytes(), newer.read_bytes()

    entries, problems = store.scan()

    assert entries == (saved,) == store.list()
    assert {problem.filename: problem.code for problem in problems} == {
        corrupt.name: "invalid_recipe_file", newer.name: "newer_format",
    }
    assert (corrupt.read_bytes(), newer.read_bytes()) == original
    copied = copy_recipe(saved.definition, saved.binding, name="Second recipe")
    store.save(copied.definition, copied.binding, expected_revision=None)
    assert {entry.binding.name for entry in store.list()} == {saved.binding.name, "Second recipe"}
