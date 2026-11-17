"""Initialize recipe execution services on first use in the recipe worker."""
from __future__ import annotations

from metroliza.recipes.contracts import StepKind


class RecipePorts:
    def __init__(self):
        self._services = {}

    @staticmethod
    def _uses_analytics(plan):
        return any(step.kind in (StepKind.LOAD_TABULAR, StepKind.LOAD_INDUSTRIAL)
                   for step in plan.definition.steps)

    def _for(self, plan):
        analytics = self._uses_analytics(plan)
        service = self._services.get(analytics)
        if service is not None:
            return service
        # RecipeRunner serializes these calls. Cancellation can run concurrently,
        # so it only signals initialized services and the runner's context.
        if analytics:
            from metroliza.recipes.tabular_adapter import create_adapter_ports

            service = create_adapter_ports()
        else:
            from metroliza.recipes.report_ports import ReportsRecipeService
            from metroliza.ui.recipe_execution_adapter import RecipeExecutionAdapter

            service = ReportsRecipeService(RecipeExecutionAdapter("import"), RecipeExecutionAdapter("export"))
        self._services[analytics] = service
        return service

    def preflight(self, plan, context):
        return self._for(plan).preflight(plan, context)

    def approve(self, plan, decision):
        return self._for(plan).approve(plan, decision)

    def execute(self, step, plan, context):
        return self._for(plan).execute(step, plan, context)

    def cancel(self):
        for service in tuple(self._services.values()):
            service.cancel()

    def finish(self, plan):
        service = self._services.get(self._uses_analytics(plan))
        if service is not None:
            service.finish(plan)
