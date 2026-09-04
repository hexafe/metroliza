"""Orchestrate threaded export workflows, rendering helpers, and Excel writing operations.

This module coordinates data retrieval (`modules.export_query_service`), grouping
(`modules.export_grouping_utils`), chart and summary planning
(`modules.export_chart_writer`, `modules.export_summary_utils`,
`modules.export_summary_sheet_planner`), and workbook output through
`modules.export_backends`.
"""

import logging
import inspect
import re
import sqlite3
import textwrap
from io import BytesIO
import os
import time
from concurrent.futures import ProcessPoolExecutor
import matplotlib
import pandas as pd
import numpy as np

# Configure Matplotlib for headless usage (must be early)
matplotlib.use('Agg')

import importlib.util

import matplotlib.pyplot as plt
import matplotlib.transforms as mtransforms
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from PyQt6.QtCore import QCoreApplication, QThread, pyqtSignal

# Type hinting imports
from typing import Any, Callable, Optional, Sequence, Union

# Module imports (cleaned to match base class signatures from context)
from modules.contracts import ExportRequest, validate_export_request
import modules.custom_logger as custom_logger
from modules.db import execute_select_with_columns, read_sql_dataframe, sqlite_connection_scope
from modules.excel_sheet_utils import unique_sheet_name
from modules.export_backends import ExcelExportBackend

# Google Drive specific imports
from modules.google_drive_export import (
    GoogleDriveAuthError,
    GoogleDriveCanceledError,
    GoogleDriveExportError,
    upload_and_convert_workbook,
)

# Google Result Utils
from modules.export_google_result_utils import (
    build_google_conversion_metadata,
    build_google_fallback_metadata,
    build_google_stage_message,
)

# Progress and Status
from modules.progress_status import build_three_line_status

# Log Context
from modules.log_context import (
    build_google_conversion_log_extra,
    get_operation_logger,
)

# Export Logging Service
from modules.export_logging_service import (
    build_export_context as _build_export_context_payload,
    log_export_stage as _log_export_stage_message,
    log_google_issue as _log_google_issue_message,
)

# Summary Utils
from modules.export_summary_utils import (
    apply_shared_x_axis_label_strategy as _apply_shared_x_axis_label_strategy,
    prepare_categorical_x_axis as _prepare_categorical_x_axis,
    resolve_extended_chart_fig_width as _resolve_extended_chart_fig_width,
    build_histogram_density_curve_payload as _build_histogram_density_curve_payload,
    build_sparse_unique_labels as _build_sparse_unique_labels,
    build_summary_panel_labels as _build_summary_panel_labels,
    build_trend_plot_payload as _build_trend_plot_payload,
    compute_measurement_summary,
    compute_normality_status,
    compute_estimated_tail_metrics,
    resolve_histogram_bin_count,
    normalize_plot_axis_values as _normalize_plot_axis_values,
    resolve_nominal_and_limits,
    render_spec_reference_lines as _render_spec_reference_lines,
    render_tolerance_band as _render_tolerance_band,
    build_tolerance_reference_legend_handles as _build_tolerance_reference_legend_handles,
)

# Summary Sheet Planner
from modules.export_summary_sheet_planner import (
    build_histogram_annotation_specs as _build_histogram_annotation_specs,
    compute_histogram_annotation_rows as _compute_histogram_annotation_rows,
    build_summary_image_anchor_plan as _build_summary_image_anchor_plan,
    build_summary_sheet_position_plan as _build_summary_sheet_position_plan,
)

# Chart Writer
from modules.export_chart_writer import (
    build_measurement_chart_format_policy as _build_measurement_chart_format_policy,
    build_measurement_chart_range_specs as _build_measurement_chart_range_specs,
    build_measurement_chart_series_specs as _build_measurement_chart_series_specs,
    build_sheet_series_range as _build_sheet_series_range,
    build_horizontal_limit_line_specs as _build_horizontal_limit_line_specs,
    insert_measurement_chart,
)

# Query Service (Fixed imports with trailing commas to prevent syntax errors)
from modules.export_query_service import (
    build_export_dataframe as _build_export_dataframe,
    build_measurement_export_dataframe as _build_measurement_export_dataframe,
    execute_export_query as _execute_export_query,
    fetch_partition_header_counts as _fetch_partition_header_counts,
    fetch_partition_values as _fetch_partition_values,
    fetch_sql_measurement_summary as _fetch_sql_measurement_summary,
)


class ExportDataThread(QThread):
    """
    Threaded worker for processing export jobs.
    Signals progress to the main UI thread.
    """
    
    # Signals for progress updates
    signal_progress = pyqtSignal(str)
    signal_finished = pyqtSignal()
    
    def __init__(self, request: ExportRequest, worker_index: int = 0):
        super().__init__()
        self._request = request
        self._worker_index = worker_index
        self._thread_name = f"ExportWorker-{worker_index}"
        self._is_running = True
        self._status_label_text = ""
        
    @property
    def request(self) -> ExportRequest:
        return self._request

    @property
    def worker_index(self) -> int:
        return self._worker_index

    def get_logger(self) -> logging.Logger:
        """Helper to get the specific logger for this thread."""
        return get_operation_logger(f"{self._thread_name}.{self._worker_index}")

    def _on_run(self, chunk_index: Optional[int] = None):
        """Core logic for processing the data chunk."""
        logger = self.get_logger()
        
        if chunk_index is not None:
            logger.info(f"Processing chunk {chunk_index}")
        
        # Fetch data using the fixed import
        # We handle the return value flexibly
        data = _build_export_dataframe(
            table_name=self._request.table_name if hasattr(self._request, 'table_name') else 'PARTS',
            filters=self._request.filters if hasattr(self._request, 'filters') else None,
            database=self._request.database if hasattr(self._request, 'database') else 'bom.db',
        )
        
        if data is not None and not data.empty:
            self._status_label_text = "Processing data..."
            self._emit_progress()
            
            # Execute export logic
            _execute_export_query(
                query=self._request.query if hasattr(self._request, 'query') else None,
                data_source=self._request.data_source if hasattr(self._request, 'data_source') else 'table',
                database=self._request.database if hasattr(self._request, 'database') else 'bom.db',
            )
            
    def run(self):
        """Entry point for the thread."""
        self._is_running = True
        try:
            if hasattr(self, '_request') and self._request:
                num_chunks = self._request.num_chunks if hasattr(self._request, 'num_chunks') else 1
                
                for chunk_idx in range(num_chunks):
                    self._on_run(chunk_index=chunk_idx)
        except Exception as e:
            logger = self.get_logger()
            logger.error(f"Worker {self._worker_index} failed: {e}", exc_info=True)
        finally:
            self._is_running = False
            
    def _emit_progress(self):
        """Emit a signal to update the UI safely."""
        self.signal_progress.emit(self._status_label_text)
        self._status_label_text = f"{self._status_label_text} (Progress)"

    def __repr__(self) -> str:
        return f"ExportDataThread(worker={self._worker_index}, name={self._thread_name})"