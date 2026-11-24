"""Industrial-cache specialization of the common native analytics recipe port."""
from metroliza.recipes.contracts import RecipeError
from metroliza.recipes.tabular_adapter import AnalyticsRecipePorts, capabilities, create_adapter_ports, resolve, validate
from metroliza.recipes.tabular_adapter import capture as _capture


def capture(request, *, name="Analiza Industrial"):
    if request.source_kind != "production_cache":
        raise RecipeError("invalid_analytics_source")
    return _capture(request, name=name)


__all__ = ["AnalyticsRecipePorts", "capture", "create_adapter_ports", "capabilities", "resolve", "validate"]
