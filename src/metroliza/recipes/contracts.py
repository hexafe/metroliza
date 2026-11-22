"""Closed, immutable recipe contracts. Private values never belong in definitions."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TypeAlias
from uuid import uuid4

FORMAT_VERSION = 1
METHOD_VERSION = 1
MAX_STEPS = 32
MAX_PARAMETERS = 64
MAX_PAYLOAD_BYTES = 262_144
MAX_VALUE_LENGTH = 8192


class RecipeError(ValueError):
    """A controlled error whose code is safe to display or record."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class ParameterMode(str, Enum):
    FIXED = "fixed"
    PROMPT = "prompt"
    DERIVED = "derived"


class ParameterType(str, Enum):
    PATH = "path"
    TEXT = "text"
    BOOLEAN = "boolean"
    INTEGER = "integer"
    NUMBER = "number"
    CHOICE = "choice"
    STRINGS = "strings"


class ParameterKey(str, Enum):
    INPUT_FOLDER = "input_folder"
    OUTPUT_FILE = "output_file"
    DATABASE_FILE = "database_file"
    EXISTING_DATABASE = "existing_database"
    SOURCE_FILE = "source_file"
    SOURCE_FILES = "source_files"
    SHEET = "sheet"
    COLUMNS = "columns"
    COLUMN_ROLES = "column_roles"
    CACHE_REFERENCE = "cache_reference"
    DATE_FROM = "date_from"
    DATE_TO = "date_to"
    FILTER_VALUES = "filter_values"
    GROUPING_RULES = "grouping_rules"
    METADATA_MODE = "metadata_mode"
    EXPORT_PRESET = "export_preset"
    EXPORT_OPTIONS = "export_options"
    ANALYTICS_REQUEST = "analytics_request"
    SOURCE_KIND = "source_kind"
    METHOD = "method"
    CONFIDENCE = "confidence"
    SAMPLE_SIZE = "sample_size"
    INCLUDE_PLOTS = "include_plots"


class DerivationRule(str, Enum):
    DATABASE_FROM_OUTPUT = "database_from_output"


class StepKind(str, Enum):
    OPEN_DATABASE = "open_database"
    PREPARE_DATABASE = "prepare_database"
    PREPARE_EXISTING_DATABASE = "prepare_existing_database"
    IMPORT_REPORTS = "import_reports"
    FILTER = "filter"
    GROUP = "group"
    EXPORT_MAIN = "export_main"
    EXPORT_HTML = "export_html"
    VERIFY_OUTPUT = "verify_output"
    LOAD_INDUSTRIAL = "load_industrial"
    LOAD_TABULAR = "load_tabular"
    ANALYZE_TABULAR = "analyze_tabular"


class DataKind(str, Enum):
    NONE = "none"
    DATABASE = "database"
    SELECTION = "selection"
    ARTIFACT = "artifact"
    TABULAR = "tabular"


@dataclass(frozen=True)
class ParameterSpec:
    key: ParameterKey
    type: ParameterType
    mode: ParameterMode = ParameterMode.PROMPT
    required: bool = True
    rule: DerivationRule | None = None


@dataclass(frozen=True)
class StepSpec:
    kind: StepKind
    input_kind: DataKind
    output_kind: DataKind


@dataclass(frozen=True)
class RecipeDefinition:
    recipe_id: str
    steps: tuple[StepSpec, ...]
    parameters: tuple[ParameterSpec, ...]
    format_version: int = FORMAT_VERSION
    method_version: int = METHOD_VERSION
    builtin: bool = False


PrivateValue: TypeAlias = str | bool | int | float | tuple[str, ...]


@dataclass(frozen=True, repr=False)
class LocalBinding:
    recipe_id: str
    name: str
    revision: int = 0
    values: tuple[tuple[ParameterKey, PrivateValue], ...] = ()

    def value(self, key: ParameterKey | str, default: PrivateValue | None = None) -> PrivateValue | None:
        return dict(self.values).get(ParameterKey(key), default)


@dataclass(frozen=True, repr=False)
class AnalyticsOutputPaths:
    dashboard: Path
    workbook: Path | None
    assets: Path


@dataclass(frozen=True, repr=False)
class ResolvedRunPlan:
    definition: RecipeDefinition
    binding: LocalBinding
    input_folder: Path | None
    output_file: Path | None
    database_file: Path | None
    assets_dir: Path | None
    flow_id: str = field(default_factory=lambda: str(uuid4()))
    run_id: str = field(default_factory=lambda: str(uuid4()))

    def value(self, key: ParameterKey | str, default: PrivateValue | None = None) -> PrivateValue | None:
        return self.binding.value(key, default)

    @property
    def appends_to_database(self) -> bool:
        return self.definition.steps[0].kind is StepKind.PREPARE_EXISTING_DATABASE

    @property
    def creates_database(self) -> bool:
        return not self.appends_to_database and any(
            step.kind in {StepKind.PREPARE_DATABASE, StepKind.IMPORT_REPORTS} for step in self.definition.steps
        )
