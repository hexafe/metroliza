"""Base classes for report parsers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
import re

import pandas


@dataclass(frozen=True)
class SourceDescriptor:
    """Neutral filesystem descriptor for one parser input."""

    source_path: str
    absolute_path: str
    directory_path: str
    file_name: str
    file_extension: str
    source_format: str


class BaseReportParser(ABC):
    """Common parser state and serialization helpers."""

    def __init__(self, file_path: str, database: str, connection=None):
        report_path = Path(file_path)

        self._source_path = str(report_path.absolute())
        self._file_path = str(report_path.absolute().parent)
        self._file_name = report_path.name
        self._date = None
        self._reference = None
        self._sample_number = None
        self._canonical_metadata = None
        self._raw_text = []
        self._blocks_text = []
        self.df = pandas.DataFrame()
        self.database = database
        self.connection = connection

    @property
    def source_path(self):
        return self._source_path

    @property
    def canonical_metadata(self):
        return self._canonical_metadata

    @canonical_metadata.setter
    def canonical_metadata(self, value):
        self._canonical_metadata = value

    @property
    def file_path(self):
        return self._file_path

    @file_path.setter
    def file_path(self, value):
        self._file_path = value

    @property
    def file_name(self):
        return self._file_name

    @file_name.setter
    def file_name(self, value):
        self._file_name = value

    @property
    def date(self):
        if self._canonical_metadata is not None:
            return getattr(self._canonical_metadata, 'report_date', self._date)
        return self._date

    @date.setter
    def date(self, value):
        self._date = value

    @property
    def reference(self):
        if self._canonical_metadata is not None:
            return getattr(self._canonical_metadata, 'reference', self._reference)
        return self._reference

    @reference.setter
    def reference(self, value):
        self._reference = value

    @property
    def sample_number(self):
        if self._canonical_metadata is not None:
            return getattr(self._canonical_metadata, 'sample_number', self._sample_number)
        return self._sample_number

    @sample_number.setter
    def sample_number(self, value):
        self._sample_number = value

    @property
    def raw_text(self):
        return self._raw_text

    @raw_text.setter
    def raw_text(self, value):
        self._raw_text = value

    @property
    def blocks_text(self):
        return self._blocks_text

    @blocks_text.setter
    def blocks_text(self, value):
        self._blocks_text = value

    # Backward-compatible aliases used across older code paths.
    @property
    def pdf_file_path(self):
        return self.file_path

    @pdf_file_path.setter
    def pdf_file_path(self, value):
        self.file_path = value

    @property
    def pdf_file_name(self):
        return self.file_name

    @pdf_file_name.setter
    def pdf_file_name(self, value):
        self.file_name = value

    @property
    def pdf_date(self):
        return self.date

    @pdf_date.setter
    def pdf_date(self, value):
        self.date = value

    @property
    def pdf_reference(self):
        return self.reference

    @pdf_reference.setter
    def pdf_reference(self, value):
        self.reference = value

    @property
    def pdf_sample_number(self):
        return self.sample_number

    @pdf_sample_number.setter
    def pdf_sample_number(self, value):
        self.sample_number = value

    @property
    def pdf_raw_text(self):
        return self.raw_text

    @pdf_raw_text.setter
    def pdf_raw_text(self, value):
        self.raw_text = value

    @property
    def pdf_blocks_text(self):
        return self.blocks_text

    @pdf_blocks_text.setter
    def pdf_blocks_text(self, value):
        self.blocks_text = value

    def get_date_from_filename(self):
        date_pattern = r"\d{4}[- _/\.]\d{1,2}[- _/\.]\d{1,2}"
        date_match = re.findall(date_pattern, self.file_name)
        date_value = date_match[-1] if date_match else "0000.00.00"
        return date_value.replace(".", "-").replace("_", "-").replace("/", "-")

    def get_sample_number_from_file(self):
        pattern = r"\d{4}[- _/\.]\d{1,2}[- _/\.]\d{1,2}_(.*?)\.(?i:pdf)"
        match = re.search(pattern, self.file_name)
        if match:
            return match.group(1)
        return "0000"

    def get_reference_from_filename(self):
        reference_pattern = r"([A-Z][A-Za-z0-9]{4}\d{1,5}(_\d{3})?)|(\d{2}[A-Za-z][._-]?\d{3}[._-]?\d{3})|(216\d{5})"
        reference_match = re.match(reference_pattern, self.file_name)
        return reference_match.group(0) if reference_match else None

    def build_source_descriptor(self):
        """Build a neutral descriptor without finalizing semantic metadata."""

        absolute_path = Path(self.source_path)
        suffix = absolute_path.suffix.lower()
        return SourceDescriptor(
            source_path=str(absolute_path),
            absolute_path=str(absolute_path),
            directory_path=str(absolute_path.parent),
            file_name=absolute_path.name,
            file_extension=suffix,
            source_format=suffix.lstrip('.') or 'unknown',
        )

    def detect_template_family(self):
        """Return parser-specific template family information."""

        raise NotImplementedError("Parser-specific template detection must be implemented by subclasses.")

    def extract_metadata(self):
        """Extract canonical report metadata after source content is available."""

        raise NotImplementedError("Parser-specific metadata extraction must be implemented by subclasses.")

    def parse_measurements(self):
        """Parse report measurements into the flat persistence payload."""

        raise NotImplementedError("Parser-specific measurement parsing must be implemented by subclasses.")

    def build_report_identity_hash(self):
        """Build a stable semantic report identity hash."""

        raise NotImplementedError("Parser-specific identity hashing must be implemented by subclasses.")

    def persist_report(self):
        """Persist parser output using the report repository."""

        raise NotImplementedError("Parser-specific persistence must be implemented by subclasses.")

    @abstractmethod
    def open_report(self):
        """Open report and populate raw_text."""

    @abstractmethod
    def split_text_to_blocks(self):
        """Parse raw_text into blocks_text."""

    def to_dict(self):
        report_dict = {
            "file_name": self.file_name,
            "date": self.date,
            "reference": self.reference,
            "blocks": [],
        }

        for block in self.blocks_text:
            report_dict["blocks"].append(
                {
                    "header_comment": block[0],
                    "dimensions": block[1:],
                }
            )
        return report_dict

    def to_df(self):
        df_list = []
        for block in self.blocks_text:
            header = ""
            for sublist in block[0]:
                if isinstance(sublist, str):
                    header += f"{sublist}, "
                else:
                    for item in sublist:
                        if isinstance(item, str):
                            header += f"{item}, "

            columns = ['AX', 'NOM', '+TOL', '-TOL', 'BONUS', 'MEAS', 'DEV', 'OUTTOL']
            df = pandas.DataFrame(block[1], columns=columns)
            df['Header'] = header[:-2]
            df['Reference'] = self.reference
            df['File location'] = self.file_path
            df['File name'] = self.file_name
            df['Date'] = self.date
            df_list.append(df)

        if df_list:
            self.df = pandas.concat(df_list)

    def to_sqlite(self):
        raise NotImplementedError("Parser-specific SQLite persistence must be implemented by subclasses.")
