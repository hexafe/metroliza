import sys
import types
import unittest


qtcore_stub = types.ModuleType('PyQt6.QtCore')


class _DummyThread:
    def __init__(self, *args, **kwargs):
        pass


class _DummyCoreApp:
    @staticmethod
    def processEvents():
        return None


def _dummy_signal(*args, **kwargs):
    class _Signal:
        def emit(self, *a, **k):
            return None

    return _Signal()


qtcore_stub.QCoreApplication = _DummyCoreApp
qtcore_stub.QThread = _DummyThread
qtcore_stub.pyqtSignal = _dummy_signal
sys.modules['PyQt6.QtCore'] = qtcore_stub

custom_logger_stub = types.ModuleType('modules.CustomLogger')


class _DummyLogger:
    def __init__(self, *args, **kwargs):
        pass


custom_logger_stub.CustomLogger = _DummyLogger
sys.modules['modules.CustomLogger'] = custom_logger_stub

from modules.ExportDataThread import (
    build_histogram_density_curve_payload,
    compute_scaled_y_limits,
)


class TestExportPlotHelpers(unittest.TestCase):
    def test_compute_scaled_y_limits_expands_symmetrically(self):
        y_min, y_max = compute_scaled_y_limits((10.0, 20.0), 0.4)

        self.assertEqual(y_min, 8.0)
        self.assertEqual(y_max, 22.0)

    def test_build_histogram_density_curve_payload_builds_curve_for_variable_data(self):
        payload = build_histogram_density_curve_payload([1.0, 1.5, 2.0, 2.5])

        self.assertIsNotNone(payload)
        self.assertEqual(len(payload['x']), 100)
        self.assertEqual(len(payload['y']), 100)

    def test_build_histogram_density_curve_payload_returns_none_for_constant_data(self):
        payload = build_histogram_density_curve_payload([3.0, 3.0, 3.0])

        self.assertIsNone(payload)


if __name__ == '__main__':
    unittest.main()
