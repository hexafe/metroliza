"""Pure parsing interface for CMM PDF tokenization/block parsing.

Input contract:
    raw_lines: list[str] (equivalent to ``CMMReportParser.pdf_raw_text``)

Output contract:
    list where each item matches legacy ``pdf_blocks_text`` shape:
    [header_comment: list, dimensions: list[list]]
"""

from __future__ import annotations

import re
from typing import Any

MEASUREMENT_LINE_MAP = {
    "X": 7,
    "Y": 7,
    "Z": 7,
    "TP": 7,
    "M": 8,
    "D": 7,
    "RN": 7,
    "DF": 8,
    "PR": 7,
    "PA": 4,
    "D1": 5,
    "A": 7,
}


def parse_raw_lines_to_blocks(raw_lines: list[str]) -> list[list[Any]]:
    """Parse raw report lines into legacy block structure."""

    def is_comment_or_header(line: str) -> bool:
        return line.startswith(("#", "*"))

    def is_dim_line(line: str) -> bool:
        return line.startswith("DIM")

    def is_numerical(line: str) -> bool:
        try:
            float(line.strip())
            return True
        except ValueError:
            return False

    def is_number(value: str) -> bool:
        try:
            float(value)
            return True
        except ValueError:
            return False

    def process_line(line: list[str]) -> list[Any]:
        processed_line: list[Any] = []

        def process_tp_line(tokens: list[str]) -> list[Any]:
            tp_qualifiers = {
                "RFS",
                "MMC",
                "LMC",
                "MMB",
                "LMB",
                "TANGENT",
                "PROJECTED",
            }
            semantic_labels = {"NOM", "+TOL", "TOL", "BONUS", "MEAS", "DEV", "OUTTOL", "ACT", "OUT"}

            numeric_values: list[float] = []
            for token in tokens[1:]:
                normalized_token = token.upper().rstrip(":")
                if is_number(token):
                    numeric_values.append(float(token))
                elif normalized_token in tp_qualifiers or normalized_token in semantic_labels:
                    continue

            if len(numeric_values) < 5:
                return []

            nom = 0.0
            if len(numeric_values) >= 6:
                nom, tol_plus, bonus, meas, dev, outtol = numeric_values[:6]
            else:
                tol_plus, bonus, meas, dev, outtol = numeric_values[:5]

            return ["TP", nom, tol_plus, "", bonus, meas, dev, outtol]

        if (line[0] in ["X", "Y", "Z"]) and len(line) == 4:
            processed_line = [line[0], float(line[1]), "", "", "", float(line[2]), float(line[3]), ""]
        elif (line[0] in ["X", "Y", "Z"]) and len(line) == 7:
            processed_line = [
                line[0],
                float(line[1]),
                float(line[2]),
                float(line[3]),
                "",
                float(line[4]),
                float(line[5]),
                float(line[6]),
            ]
        elif line[0].startswith("TP"):
            processed_line = process_tp_line(line)
        elif line[0] == "M" and len(line) == 7:
            processed_line = [
                line[0],
                float(line[1]),
                float(line[2]),
                float(line[3]),
                "",
                float(line[4]),
                float(line[5]),
                float(line[6]),
            ]
        elif line[0] == "M" and len(line) == 8:
            processed_line = [
                line[0],
                float(line[1]),
                float(line[2]),
                float(line[3]),
                float(line[4]),
                float(line[5]),
                float(line[6]),
                float(line[7]),
            ]
        elif line[0] == "D" and len(line) == 7:
            processed_line = [
                line[0],
                float(line[1]),
                float(line[2]),
                float(line[3]),
                "",
                float(line[4]),
                float(line[5]),
                float(line[6]),
            ]
        elif line[0] == "RN" and len(line) == 7:
            processed_line = [
                line[0],
                float(line[1]),
                float(line[2]),
                float(line[3]),
                "",
                float(line[4]),
                float(line[5]),
                float(line[6]),
            ]
        elif line[0] == "DF" and len(line) == 8:
            processed_line = [
                line[0],
                float(line[1]),
                float(line[2]),
                float(line[3]),
                float(line[4]),
                float(line[5]),
                float(line[6]),
                float(line[7]),
            ]
        elif line[0] == "DF" and len(line) == 7:
            processed_line = [
                line[0],
                float(line[1]),
                float(line[2]),
                float(line[3]),
                "0",
                float(line[4]),
                float(line[5]),
                float(line[6]),
            ]
        elif line[0] == "PR" and len(line) == 7:
            processed_line = [
                line[0],
                float(line[1]),
                float(line[2]),
                float(line[3]),
                "",
                float(line[4]),
                float(line[5]),
                float(line[6]),
            ]
        elif line[0] == "PR" and len(line) == 4:
            processed_line = [line[0], float(line[1]), "", "", "", float(line[2]), float(line[3]), ""]
        elif line[0] == "PA" and len(line) == 4:
            processed_line = [line[0], float(line[1]), "", "", "", float(line[2]), float(line[3]), ""]
        elif line[0] == "D1" and len(line) == 5 and line[1].isnumeric():
            processed_line = [line[0], float(line[1]), float(line[2]), float(line[3]), "", float(line[4]), "", ""]
        elif line[0] == "A" and len(line) == 7:
            processed_line = [
                line[0],
                float(line[1]),
                float(line[2]),
                float(line[3]),
                "0",
                float(line[4]),
                float(line[5]),
                float(line[6]),
            ]
        return processed_line

    def extract_measurement_tokens_and_raw_lines_consumed(
        lines: list[str], preserve_non_numeric_tokens: bool = False
    ) -> tuple[list[str], int]:
        if not lines:
            return [], 0

        code_tokens = lines[0].split()
        if not code_tokens:
            return [], 0

        code, *first_line_tokens = code_tokens
        parsed_tokens: list[str] = [code]
        raw_lines_consumed = 1
        max_token_count = MEASUREMENT_LINE_MAP.get(code, 0)
        max_numeric_count = max(max_token_count - 1, 0) if max_token_count else 0

        def numeric_tokens_consumed() -> int:
            return sum(1 for token in parsed_tokens[1:] if is_number(token))

        def append_tokens(tokens: list[str]) -> None:
            for token in tokens:
                if is_number(token):
                    parsed_tokens.append(token)
                    if max_numeric_count and numeric_tokens_consumed() >= max_numeric_count:
                        break
                elif preserve_non_numeric_tokens:
                    parsed_tokens.append(token)
                    if max_numeric_count and numeric_tokens_consumed() >= max_numeric_count:
                        break

        append_tokens(first_line_tokens)

        for raw_line in lines[1:]:
            if max_numeric_count and numeric_tokens_consumed() >= max_numeric_count:
                break

            raw_line_tokens = raw_line.split()
            if not raw_line_tokens:
                raw_lines_consumed += 1
                continue

            if is_comment_or_header(raw_line) or is_dim_line(raw_line) or raw_line_tokens[0] in MEASUREMENT_LINE_MAP:
                break

            raw_lines_consumed += 1
            append_tokens(raw_line_tokens)

        return parsed_tokens, raw_lines_consumed

    def extract_header_comment(lines: list[str]) -> tuple[str, int]:
        header: list[str] = []
        counter = 0
        for i, line in enumerate(lines):
            if not is_dim_line(line):
                if i:
                    line = line.replace("#", "").replace("*", "")
                header.append(line)
            else:
                counter = i - 1
                break
        return " ".join(header), counter

    pdf_blocks_text: list[list[Any]] = []
    text_block: list[Any] = []
    dim_block: list[Any] = []
    header_comment: list[Any] = []
    raw_lines_to_skip = 0

    for index, line in enumerate(raw_lines):
        if raw_lines_to_skip:
            raw_lines_to_skip -= 1
            continue

        prev_line = raw_lines[index - 1] if index > 0 else None

        if is_comment_or_header(line):
            line, raw_lines_to_skip = extract_header_comment(raw_lines[index : index + 10])

        if index == len(raw_lines) - 1:
            if text_block:
                text_block = [header_comment] + [dim_block]
                pdf_blocks_text.append(text_block)
                text_block, header_comment, dim_block = [], [], []

        if not is_comment_or_header(line) and len(line.split()) == 3:
            continue

        if text_block:
            if is_comment_or_header(line) or is_dim_line(line):
                if is_comment_or_header(line) and prev_line is not None and is_comment_or_header(prev_line):
                    formatted_line = re.sub(r"^[#*/]+", "", line).strip()
                    header_comment.append([formatted_line])

                if is_dim_line(line) and prev_line is not None and not is_comment_or_header(prev_line):
                    text_block = [header_comment] + [dim_block]
                    pdf_blocks_text.append(text_block)
                    text_block, dim_block = [], []
                    text_block.append(header_comment)

                if is_comment_or_header(line) and prev_line is not None and not is_comment_or_header(prev_line):
                    text_block = [header_comment] + [dim_block]
                    pdf_blocks_text.append(text_block)
                    text_block, header_comment, dim_block = [], [], []
                    formatted_line = re.sub(r"^[#*/]+", "", line).strip()
                    header_comment.append([formatted_line])
                    text_block.append(header_comment)

            else:
                tokens = line.split()
                if tokens and tokens[0] in MEASUREMENT_LINE_MAP:
                    candidate_lines = raw_lines[index:]
                    preserve_non_numeric_tokens = tokens[0].startswith("TP")
                    parsed_tokens, raw_lines_consumed = extract_measurement_tokens_and_raw_lines_consumed(
                        candidate_lines,
                        preserve_non_numeric_tokens=preserve_non_numeric_tokens,
                    )

                    raw_lines_to_skip = max(raw_lines_consumed - 1, 0)
                    temp_line = process_line(parsed_tokens)
                    if temp_line:
                        dim_block.append(temp_line)
        else:
            if not pdf_blocks_text:
                if is_comment_or_header(line):
                    formatted_line = re.sub(r"^[#*/]+", "", line).strip()
                    header_comment.append([formatted_line])
                    text_block.append(header_comment)
                elif is_dim_line(line):
                    header_comment.append("NO HEADER")
                    text_block.append(header_comment)
            else:
                if is_dim_line(line) or is_comment_or_header(line):
                    text_block = [header_comment] + [dim_block]
                    pdf_blocks_text.append(text_block)
                    text_block, dim_block = [], []
                if is_comment_or_header(line):
                    text_block, header_comment, dim_block = [], [], []
                    formatted_line = re.sub(r"^[#*/]+", "", line).strip()
                    header_comment.append([formatted_line])

    if text_block:
        candidate_block = [header_comment] + [dim_block]
        if not pdf_blocks_text or pdf_blocks_text[-1] != candidate_block:
            pdf_blocks_text.append(candidate_block)

    add_tolerances_to_blocks(pdf_blocks_text)
    return pdf_blocks_text


def add_tolerances_to_blocks(pdf_blocks_text: list[list[Any]]) -> list[list[Any]]:
    """Mutate and return parsed blocks by applying tolerance normalization."""

    def is_missing(value: Any) -> bool:
        return value in ("", None)

    for block in pdf_blocks_text:
        tol_plus = 0
        tol_minus = None
        bonus = None
        if block[1]:
            if block[1][-1][0] == "TP":
                block[1][-1][3] = 0
                tol_plus = block[1][-1][2] * 0.5
                tol_minus = -tol_plus
                bonus = block[1][-1][4]

                for measurement_line in block[1]:
                    if is_missing(measurement_line[2]):
                        measurement_line[2] = tol_plus
                        measurement_line[3] = tol_minus
                        measurement_line[4] = bonus
            else:
                saw_explicit_tol_source = False
                for measurement_line in block[1]:
                    if not is_missing(measurement_line[2]):
                        tol_plus = measurement_line[2]
                        saw_explicit_tol_source = True
                    if not is_missing(measurement_line[3]):
                        tol_minus = measurement_line[3]
                        saw_explicit_tol_source = True
                    if not is_missing(measurement_line[4]):
                        bonus = measurement_line[4]

                if bonus is None and saw_explicit_tol_source:
                    bonus = 0

                for measurement_line in block[1]:
                    if is_missing(measurement_line[2]) and tol_plus is not None:
                        measurement_line[2] = tol_plus
                    if is_missing(measurement_line[3]) and tol_minus is not None:
                        measurement_line[3] = tol_minus
                    if is_missing(measurement_line[4]) and bonus is not None:
                        measurement_line[4] = bonus
    return pdf_blocks_text
