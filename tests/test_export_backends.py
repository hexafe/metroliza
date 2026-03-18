import unittest
from unittest.mock import patch

from modules.export_backends import ExcelExportBackend


class TestExcelExportBackend(unittest.TestCase):
    def test_create_writer_enables_nan_inf_guard(self):
        backend = ExcelExportBackend()

        with patch('modules.export_backends.pd.ExcelWriter') as mock_writer:
            backend.create_writer('out.xlsx')

        mock_writer.assert_called_once_with(
            'out.xlsx',
            engine='xlsxwriter',
            engine_kwargs={'options': {'nan_inf_to_errors': True}},
        )


if __name__ == '__main__':
    unittest.main()
