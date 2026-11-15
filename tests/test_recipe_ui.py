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
