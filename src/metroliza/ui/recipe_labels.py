"""Polish labels shared by the recipe editor and run form."""
from PyQt6.QtWidgets import QComboBox

from metroliza.recipes.contracts import ParameterKey, ParameterMode, StepKind

PARAMETER_LABELS = {
    ParameterKey.INPUT_FOLDER: "Folder raportów",
    ParameterKey.OUTPUT_FILE: "Plik wynikowy",
    ParameterKey.DATABASE_FILE: "Baza danych",
    ParameterKey.EXISTING_DATABASE: "Istniejąca baza",
    ParameterKey.SOURCE_FILE: "Plik źródłowy",
    ParameterKey.SHEET: "Arkusz",
    ParameterKey.COLUMNS: "Kolumny",
    ParameterKey.COLUMN_ROLES: "Przeznaczenie kolumn",
    ParameterKey.CACHE_REFERENCE: "Zapisane dane źródłowe",
    ParameterKey.DATE_FROM: "Data początkowa",
    ParameterKey.DATE_TO: "Data końcowa",
    ParameterKey.FILTER_VALUES: "Filtry",
    ParameterKey.GROUPING_RULES: "Kolumny grupowania",
    ParameterKey.METADATA_MODE: "Tryb importu",
    ParameterKey.EXPORT_PRESET: "Profil eksportu",
    ParameterKey.EXPORT_OPTIONS: "Ustawienia eksportu",
    ParameterKey.ANALYTICS_REQUEST: "Ustawienia analizy",
    ParameterKey.SOURCE_KIND: "Rodzaj źródła",
    ParameterKey.METHOD: "Metoda analizy",
    ParameterKey.CONFIDENCE: "Poziom ufności",
    ParameterKey.SAMPLE_SIZE: "Liczebność próby",
    ParameterKey.INCLUDE_PLOTS: "Dołącz wykresy",
}
GROUP_LABELS = {"DATE": "Data", "PART_NAME": "Nazwa części", "REFERENCE": "Numer referencyjny",
                 "REVISION": "Rewizja", "SAMPLE_NUMBER": "Numer próbki", "TEMPLATE_VARIANT": "Wariant szablonu"}
CHOICE_LABELS = {
    ParameterKey.EXPORT_PRESET: {"fast_diagnostics": "Szybka diagnostyka", "full_report": "Pełny raport",
                                 "html_dashboard_only": "Tylko raport HTML"},
    ParameterKey.SOURCE_KIND: {"tabular_file": "Plik CSV lub Excel", "production_cache": "Dane przemysłowe"},
    ParameterKey.METADATA_MODE: {"light": "Szybki, bez OCR", "complete": "Pełny, z OCR w razie potrzeby"},
}
MODE_LABELS = {
    ParameterMode.PROMPT: "Pytaj przy każdym uruchomieniu",
    ParameterMode.FIXED: "Używaj zapisanej wartości",
    ParameterMode.DERIVED: "Ustal automatycznie",
}
STEP_LABELS = {
    StepKind.PREPARE_DATABASE: "Sprawdzanie źródła przed importem",
    StepKind.PREPARE_EXISTING_DATABASE: "Sprawdzanie bazy i źródła przed importem",
    StepKind.OPEN_DATABASE: "Sprawdzanie bazy",
    StepKind.IMPORT_REPORTS: "Import raportów",
    StepKind.FILTER: "Filtrowanie raportów",
    StepKind.GROUP: "Grupowanie raportów",
    StepKind.EXPORT_MAIN: "Tworzenie Excela",
    StepKind.EXPORT_HTML: "Tworzenie dashboardu",
    StepKind.VERIFY_OUTPUT: "Sprawdzanie wyniku",
    StepKind.LOAD_INDUSTRIAL: "Odczyt danych przemysłowych",
    StepKind.LOAD_TABULAR: "Odczyt danych tabelarycznych",
    StepKind.ANALYZE_TABULAR: "Analiza i eksport",
}


def choice_editor(key, value):
    """Keep the stored option independent of its visible name."""
    editor = QComboBox()
    for token, label in CHOICE_LABELS[key].items():
        editor.addItem(label, token)
    if value and editor.findData(value) < 0:
        editor.addItem(str(value), value)
    editor.setCurrentIndex(editor.findData(value))
    return editor


def format_parameter_list(key, values):
    if key is ParameterKey.GROUPING_RULES:
        return ", ".join(GROUP_LABELS.get(value, value) for value in values)
    return ", ".join(values)


def parse_parameter_list(key, text):
    values = tuple(word.strip() for word in text.split(",") if word.strip())
    if key is ParameterKey.GROUPING_RULES:
        tokens = {label.casefold(): token for token, label in GROUP_LABELS.items()}
        return tuple(tokens.get(value.casefold(), value.upper()) for value in values)
    return values
