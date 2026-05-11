"""In-memory CSV/Excel grouping dialog for tabular analytics."""

from __future__ import annotations

import pandas as pd

from modules.data_grouping import DataGrouping
from modules.tabular_analytics_service import build_tabular_grouping_dataframe


class TabularAnalyticsGroupingDialog(DataGrouping):
    """Reuse the export grouping workflow for loaded CSV/Excel rows."""

    def __init__(self, parent=None, *, dataframe: pd.DataFrame | None = None):
        self.source_dataframe = dataframe.copy() if isinstance(dataframe, pd.DataFrame) else pd.DataFrame()
        super().__init__(parent=parent, db_file="")

    def read_data_to_df(self):
        self.df = build_tabular_grouping_dataframe(self.source_dataframe)

    def use_grouping(self):
        self.hide()
        parent = self.parent()
        if parent is not None:
            parent.set_df_for_grouping(self.df)
            parent.set_grouping_applied(True)
        self.accept()

    def dont_use_grouping(self):
        self.hide()
        parent = self.parent()
        if parent is not None:
            parent.set_df_for_grouping(None)
            parent.set_grouping_applied(False)
        self.accept()

    def refresh_data(self):
        self.read_data_to_df()
        self.add_default_group()
        self._restore_saved_grouping_state()
        self.populate_list_widgets()


__all__ = ["TabularAnalyticsGroupingDialog"]
