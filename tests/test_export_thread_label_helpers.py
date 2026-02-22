import sys
import types
import unittest


# Minimal stubs for optional runtime dependencies used by ExportDataThread imports.
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


from modules.ExportDataThread import all_measurements_within_limits, build_sparse_unique_labels


class TestExportThreadLabelHelpers(unittest.TestCase):
    def test_build_sparse_unique_labels_blanks_repeated_values(self):
        labels = ['1', '1', '2', '2', '2', '3']

        result = build_sparse_unique_labels(labels)

        self.assertEqual(result, ['1', '', '2', '', '', '3'])

    def test_build_sparse_unique_labels_keeps_first_occurrence_order(self):
        labels = ['A', 'B', 'A', 'C', 'B']

        result = build_sparse_unique_labels(labels)

        self.assertEqual(result, ['A', 'B', '', 'C', ''])


class TestExportThreadToleranceHelpers(unittest.TestCase):
    def test_all_measurements_within_limits_true_when_all_values_in_range(self):
        self.assertTrue(all_measurements_within_limits([1.0, 1.1, 0.9], 0.8, 1.2))

    def test_all_measurements_within_limits_false_when_any_value_out_of_range(self):
        self.assertFalse(all_measurements_within_limits([1.0, 1.5, 0.9], 0.8, 1.2))



if __name__ == '__main__':
    unittest.main()
