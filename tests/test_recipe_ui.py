"""Shared-controller ownership and dynamic form contracts (Qt surface)."""
from metroliza.recipes.builtin_recipes import REPORTS_EXCEL_MAIN, builtin_binding
from metroliza.recipes.contracts import ParameterKey
from metroliza.recipes.run_state import RunRecord, RunState
from metroliza.recipes.storage import StoredRecipe
from metroliza.ui.recipe_controller import RecipeController
from metroliza.ui.recipe_library_page import RecipeLibraryPage
from metroliza.ui.recipe_runner_page import RecipeRunnerPage


class Runner:
    on_event = None
    plan = None
    record = None
    review = None

    def cancel(self):
        if self.record:
            from dataclasses import replace
            self.record = replace(self.record, state=RunState.CANCELLED, ownership=False)


def test_controller_keeps_owner_until_native_completion(qapplication_session, monkeypatch):
    from types import SimpleNamespace
    from metroliza.ui import detached_threads

    controller = RecipeController(Runner())
    deleted, pending, idle = [], [], []
    task = SimpleNamespace(deleteLater=lambda: deleted.append(True))
    controller._task = task
    controller.idle.connect(lambda: idle.append(True))

    def defer(threads, callback):
        assert threads == (task,)
        pending.append(callback)

    monkeypatch.setattr(detached_threads, "run_when_finished", defer)
    controller._finished()
    assert controller.busy and not controller.request_close()
    assert not deleted and not idle
    pending[0]()
    assert controller.request_close() and not controller.busy
    assert deleted == [True] and idle == [True]


def test_micro_form_has_two_prompted_fields_and_preserves_private_plan(qapplication_session, tmp_path):
    controller = RecipeController(Runner())
    page = RecipeRunnerPage(controller)
    assert controller.launch("reports_excel_main")
    assert set(page.fields) == {ParameterKey.INPUT_FOLDER, ParameterKey.OUTPUT_FILE}
    page.fields[ParameterKey.INPUT_FOLDER][0].setText(str(tmp_path / "reports"))
    page.fields[ParameterKey.OUTPUT_FILE][0].setText(str(tmp_path / "result.xlsx"))
    assert controller.prepare(page._values())
    assert controller.plan.database_file == tmp_path / "result.db"
    assert "result.db" in page.database.text()
    page.close()


def test_library_and_quick_flow_raise_existing_run_without_duplicate(qapplication_session):
    runner = Runner()
    controller = RecipeController(runner)
    assert controller.launch("reports_excel_main")
    original = controller.definition
    runner.record = RunRecord("flow", "run", RunState.RUNNING, ownership=True)
    controller.last_record = runner.record
    raised = []
    controller.view_requested.connect(lambda: raised.append(True))
    assert not controller.launch("reports_dashboard_html")
    assert controller.definition is original and raised == [True]
    assert not controller.request_close()
    controller.cancel()
    assert controller.request_close()


def test_unavailable_catalogue_adapter_cannot_run_and_copy_edit_hooks_are_explicit(qapplication_session):
    controller = RecipeController(Runner())
    entry = StoredRecipe(REPORTS_EXCEL_MAIN, builtin_binding(REPORTS_EXCEL_MAIN))
    page = RecipeLibraryPage(controller, lambda: (entry,), available=lambda _definition: False)
    page.list.setCurrentRow(0)
    assert not page.run_button.isEnabled()
    assert not page.edit_button.isEnabled()
    copies = []
    page.copy_requested.connect(copies.append)
    page.copy_button.click()
    assert copies == [entry]
    page.close()


def test_copy_ready_refreshes_actual_form_paths_before_explicit_continue(qapplication_session, tmp_path, monkeypatch):
    from metroliza.recipes.bindings import resolve_plan
    from metroliza.recipes.ports import PreflightResult, StepResult, StepStatus
    from metroliza.recipes.contracts import StepKind
    from metroliza.recipes.runner import RecipeRunner

    effects = []

    class Ports:
        def preflight(self, plan, context):
            effects.append(("preflight", plan.run_id))
            return PreflightResult(True)

        def execute(self, step, plan, context):
            effects.append((step.kind, plan.run_id))
            if step.kind is StepKind.IMPORT_REPORTS:
                plan.database_file.write_bytes(b"synthetic owned database")
            elif step.kind is StepKind.EXPORT_MAIN:
                from zipfile import ZipFile
                with ZipFile(plan.output_file, "w") as archive:
                    archive.writestr("[Content_Types].xml", "<Types/>")
                    archive.writestr("xl/workbook.xml", "<workbook/>")
            return StepResult(StepStatus.COMPLETED, artifact_verified=step.kind is StepKind.VERIFY_OUTPUT)

        def cancel(self):
            pass

    source = tmp_path / "reports"
    source.mkdir()
    binding = builtin_binding(REPORTS_EXCEL_MAIN, str(source), str(tmp_path / "result.xlsx"))
    plan = resolve_plan(REPORTS_EXCEL_MAIN, binding)
    plan.database_file.write_bytes(b"existing complete database")
    runner = RecipeRunner(Ports())
    controller = RecipeController(runner)
    page = RecipeRunnerPage(controller)
    controller.launch(REPORTS_EXCEL_MAIN, binding)
    try:
        assert runner.start(plan).decision == "collision"
        copied = runner.resume("new_copy")
        assert copied.decision == "copy_ready" and not effects
        controller._returned(copied)
        actual = runner.plan
        assert controller.binding == actual.binding
        assert page.fields[ParameterKey.OUTPUT_FILE][0].text() == str(actual.output_file)
        assert str(actual.database_file) in page.database.text()
        assert str(actual.output_file) in page.database.text()
        assert "(1)" in page.database.text()
        assert not actual.database_file.exists() and not actual.output_file.exists()
        assert page.continue_button.isVisibleTo(page)
        pending = []
        monkeypatch.setattr(controller, "_submit", lambda operation: pending.append(operation) or True)
        assert controller.resume("continue")
        assert not effects  # Scheduling still leaves the reviewed plan untouched.
        completed = pending[0]()
        assert completed.state is RunState.COMPLETED
        assert actual.database_file.is_file() and actual.output_file.is_file()
        assert effects and all(run_id == actual.run_id for _kind, run_id in effects)
    finally:
        runner.cancel()
        page.close()


def test_admitted_controller_cancel_before_worker_start_is_not_lost(qapplication_session, tmp_path, monkeypatch):
    from metroliza.recipes.runner import RecipeRunner

    class Ports:
        def cancel(self):
            pass

        def preflight(self, *_args):
            raise AssertionError("cancelled admission must not scan or write")

    runner = RecipeRunner(Ports())
    controller = RecipeController(runner)
    controller.launch("reports_excel_main")
    assert controller.prepare({ParameterKey.INPUT_FOLDER: str(tmp_path / "input"),
                               ParameterKey.OUTPUT_FILE: str(tmp_path / "result.xlsx")})
    pending = []
    monkeypatch.setattr(controller, "_submit", lambda operation: pending.append(operation) or True)
    assert controller.start()
    controller.cancel()
    record = pending[0]()
    assert record.state is RunState.CANCELLED
    assert not controller.plan.database_file.exists()


def test_all_catalog_home_and_favorite_launches_refresh_active_database(qapplication_session, tmp_path):
    from metroliza.ui.recipe_library_page import RecipeQuickFlows
    from PyQt6.QtWidgets import QPushButton

    current = [tmp_path / "first.db"]
    runner = Runner()
    controller = RecipeController(runner, active_database=lambda: current[0])
    entry = StoredRecipe(REPORTS_EXCEL_MAIN, builtin_binding(REPORTS_EXCEL_MAIN))
    library = RecipeLibraryPage(controller, (entry,))
    library.list.setCurrentRow(0)
    library.run_button.click()
    assert runner.active_database == current[0]
    quick = RecipeQuickFlows(controller, (entry,))
    current[0] = tmp_path / "second.db"
    quick.findChildren(QPushButton)[0].click()
    assert runner.active_database == current[0]
    quick.set_favorites({REPORTS_EXCEL_MAIN.recipe_id})
    current[0] = tmp_path / "third.db"
    quick.favorite_buttons.itemAt(0).widget().click()
    assert runner.active_database == current[0]
    library.close()
    quick.close()


def test_active_database_refresh_precedes_resolver_and_start_admission(qapplication_session, tmp_path):
    current = [tmp_path / "current.db"]
    runner = Runner()
    entry = StoredRecipe(REPORTS_EXCEL_MAIN, builtin_binding(REPORTS_EXCEL_MAIN))

    def resolver(_identity):
        assert runner.active_database == current[0]
        return entry

    controller = RecipeController(runner, resolver=resolver, active_database=lambda: current[0])
    assert controller.launch("private-recipe-id")
    assert controller.prepare({ParameterKey.INPUT_FOLDER: str(tmp_path / "input"),
                               ParameterKey.OUTPUT_FILE: str(tmp_path / "result.xlsx")})
    errors = []
    controller.failed.connect(errors.append)
    current[0] = tmp_path / "result.db"
    assert not controller.start()
    assert errors == ["active_database_alias"]


def test_existing_favorite_resolves_saved_fixed_filter_and_output_revision(qapplication_session, tmp_path):
    from metroliza.recipes.contracts import ParameterMode
    from metroliza.recipes.editor_service import RecipeEditorService
    from metroliza.recipes.storage import RecipeStore, copy_recipe
    from metroliza.ui.recipe_library_page import RecipeQuickFlows

    store = RecipeStore(tmp_path / "private")
    copied = copy_recipe(REPORTS_EXCEL_MAIN, builtin_binding(REPORTS_EXCEL_MAIN,
        str(tmp_path / "input"), str(tmp_path / "first.xlsx")), name="Saved favorite")
    editor = RecipeEditorService(copied)
    editor.configure_reports(dates=True, grouping_columns=(), additional_html=False)
    for key in (ParameterKey.DATE_FROM, ParameterKey.DATE_TO, ParameterKey.OUTPUT_FILE):
        editor.set_mode(key, ParameterMode.FIXED)
    editor.set_value(ParameterKey.DATE_FROM, "2024-01-01")
    editor.set_value(ParameterKey.DATE_TO, "2024-01-31")
    first = editor.save(store)
    controller = RecipeController(Runner(), resolver=store.load)
    quick = RecipeQuickFlows(controller, store.list)
    quick.set_favorites({first.definition.recipe_id})
    original_button = quick.favorite_buttons.itemAt(0).widget()
    editor.set_value(ParameterKey.DATE_FROM, "2024-01-02")
    editor.set_value(ParameterKey.OUTPUT_FILE, str(tmp_path / "latest.xlsx"))
    latest = editor.save(store)
    original_button.click()  # No shortcut reconstruction or process restart.
    assert latest.binding.revision == first.binding.revision + 1
    assert controller.binding == latest.binding
    assert controller.binding.value(ParameterKey.DATE_FROM) == "2024-01-02"
    assert controller.binding.value(ParameterKey.OUTPUT_FILE) == str(tmp_path / "latest.xlsx")
    assert next(p for p in controller.definition.parameters
                if p.key is ParameterKey.DATE_FROM).mode is ParameterMode.FIXED
    quick.close()


def test_deleted_favorite_reports_closed_error_without_launching_stale_snapshot(qapplication_session, tmp_path):
    from metroliza.recipes.storage import RecipeStore, copy_recipe
    from metroliza.ui.recipe_library_page import RecipeQuickFlows

    store = RecipeStore(tmp_path / "private")
    copied = copy_recipe(REPORTS_EXCEL_MAIN, builtin_binding(REPORTS_EXCEL_MAIN), name="Private")
    saved = store.save(copied.definition, copied.binding, expected_revision=None)
    controller = RecipeController(Runner(), resolver=store.load)
    controller.launch("reports_excel_main")
    previous = controller.binding
    quick = RecipeQuickFlows(controller, store.list)
    quick.set_favorites({saved.definition.recipe_id})
    errors = []
    controller.failed.connect(errors.append)
    (store.root / f"{saved.definition.recipe_id}.json").unlink()
    quick.favorite_buttons.itemAt(0).widget().click()
    assert errors == ["recipe_not_found"]
    assert controller.binding is previous
    quick.close()


def test_busy_favorite_raises_current_flow_before_any_saved_revision_read(qapplication_session):
    from metroliza.ui.recipe_library_page import RecipeQuickFlows
    from metroliza.recipes.storage import copy_recipe

    def resolver(_identity):
        raise AssertionError("busy controller must retain its current owner")
    controller = RecipeController(Runner(), resolver=resolver)
    controller.launch("reports_excel_main")
    previous = controller.binding
    favorite = copy_recipe(REPORTS_EXCEL_MAIN, previous, name="Private favorite")
    quick = RecipeQuickFlows(controller, (favorite,))
    quick.set_favorites({favorite.definition.recipe_id})
    controller.last_record = RunRecord("flow", "run", RunState.RUNNING, ownership=True)
    raised = []
    controller.view_requested.connect(lambda: raised.append(True))
    quick.favorite_buttons.itemAt(0).widget().click()
    assert raised == [True] and controller.binding is previous
    assert controller.busy
    controller.last_record = None
    quick.close()
