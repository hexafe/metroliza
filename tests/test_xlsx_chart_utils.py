from modules.xlsx_chart_utils import apply_chart_options, create_workbook_chart, insert_chart


class _Chart:
    def __init__(self, spec):
        self.spec = spec
        self.calls = []

    def set_title(self, value):
        self.calls.append(("title", value))

    def set_x_axis(self, value):
        self.calls.append(("x_axis", value))

    def set_y_axis(self, value):
        self.calls.append(("y_axis", value))

    def set_legend(self, value):
        self.calls.append(("legend", value))

    def set_size(self, value):
        self.calls.append(("size", value))

    def set_style(self, value):
        self.calls.append(("style", value))


class _Workbook:
    def __init__(self):
        self.specs = []

    def add_chart(self, spec):
        self.specs.append(spec)
        return _Chart(spec)


class _Worksheet:
    def __init__(self):
        self.inserted = None

    def insert_chart(self, row, column, chart, options):
        self.inserted = (row, column, chart, options)


def test_xlsx_chart_utils_create_apply_and_insert_chart() -> None:
    workbook = _Workbook()
    chart = create_workbook_chart(workbook, "scatter", subtype="straight_with_markers")

    apply_chart_options(
        chart,
        title={"name": "Title"},
        x_axis={"name": "X"},
        y_axis={"name": "Y"},
        legend={"none": True},
        size={"width": 520},
        style=10,
    )
    worksheet = _Worksheet()
    insert_chart(worksheet, 2, 3, chart, x_offset=8, y_scale=1.25)

    assert workbook.specs == [{"type": "scatter", "subtype": "straight_with_markers"}]
    assert ("title", {"name": "Title"}) in chart.calls
    assert ("style", 10) in chart.calls
    assert worksheet.inserted == (2, 3, chart, {"x_offset": 8, "y_scale": 1.25})
