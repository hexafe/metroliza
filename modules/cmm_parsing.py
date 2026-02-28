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
        elif line[0] == "TP" and len(line) == 6:
            processed_line = [
                line[0],
                float(line[1]),
                float(line[2]),
                "",
                float(line[3]),
                float(line[4]),
                float(line[4]),
                float(line[5]),
            ]
        elif line[0] == "TP" and len(line) == 7:
            processed_line = [
                line[0],
                float(line[1]),
                float(line[2]),
                "",
                float(line[3]),
                float(line[4]),
                float(line[5]),
                float(line[6]),
            ]
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

    def extract_numerical_lines(lines: list[str]) -> tuple[list[str], int]:
        prefixes = ["X", "Y", "Z", "TP", "M", "D", "RN", "DF", "PR", "PA", "D1", "A"]
        numerical_lines: list[str] = []
        counter = 0
        for i, line in enumerate(lines):
            if any(line.startswith(p) for p in prefixes) and not i:
                numerical_lines.append(line)
            elif not is_numerical(line):
                counter = i - 1
                break
            else:
                numerical_lines.append(line)
        return numerical_lines, counter

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
    counter = 0

    for index, line in enumerate(raw_lines):
        if counter:
            counter -= 1
            continue

        if is_comment_or_header(line):
            line, counter = extract_header_comment(raw_lines[index : index + 10])

        if index == len(raw_lines) - 1:
            if text_block:
                text_block = [header_comment] + [dim_block]
                pdf_blocks_text.append(text_block)
                text_block, header_comment, dim_block = [], [], []

        if not is_comment_or_header(line) and len(line.split()) == 3:
            continue

        if text_block:
            if is_comment_or_header(line) or is_dim_line(line):
                if is_comment_or_header(line) and raw_lines[index - 1] and is_comment_or_header(raw_lines[index - 1]):
                    formatted_line = re.sub(r"^[#*/]+", "", line).strip()
                    header_comment.append([formatted_line])

                if is_dim_line(line) and raw_lines[index - 1] and not is_comment_or_header(raw_lines[index - 1]):
                    text_block = [header_comment] + [dim_block]
                    pdf_blocks_text.append(text_block)
                    text_block, dim_block = [], []
                    text_block.append(header_comment)

                if is_comment_or_header(line) and raw_lines[index - 1] and not is_comment_or_header(raw_lines[index - 1]):
                    text_block = [header_comment] + [dim_block]
                    pdf_blocks_text.append(text_block)
                    text_block, header_comment, dim_block = [], [], []
                    formatted_line = re.sub(r"^[#*/]+", "", line).strip()
                    header_comment.append([formatted_line])
                    text_block.append(header_comment)

            else:
                if line in MEASUREMENT_LINE_MAP:
                    next_lines = raw_lines[index : index + MEASUREMENT_LINE_MAP[line]]
                    line_split: list[str] = []
                    for item in next_lines:
                        line_split.extend(item.split())

                    if line_split[0] == "TP":
                        line_split[1] = "0"
                        if not is_number(line_split[3]):
                            line_split.pop(3)
                            line_split.pop(3)
                            line_split.append(line_split[-1])
                            if float(line_split[4]) > float(line_split[2]):
                                line_split.append(str(float(line_split[4]) - float(line_split[2])))
                            else:
                                line_split.append("0")
                    next_lines, counter = extract_numerical_lines(line_split)
                    temp_line = process_line(next_lines)
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

    add_tolerances_to_blocks(pdf_blocks_text)
    return pdf_blocks_text


def add_tolerances_to_blocks(pdf_blocks_text: list[list[Any]]) -> list[list[Any]]:
    """Mutate and return parsed blocks by applying tolerance normalization."""
    for block in pdf_blocks_text:
        tol_plus = 0
        tol_minus = 0
        bonus = 0
        if block[1]:
            if block[1][-1][0] == "TP":
                block[1][-1][3] = 0
                tol_plus = block[1][-1][2] * 0.5
                tol_minus = -tol_plus
                bonus = block[1][-1][4]

                for measurement_line in block[1]:
                    if not measurement_line[2]:
                        measurement_line[2] = tol_plus
                        measurement_line[3] = tol_minus
                        measurement_line[4] = bonus
            else:
                for measurement_line in block[1]:
                    if not measurement_line[2]:
                        measurement_line[2] = tol_plus
                    elif not measurement_line[3]:
                        measurement_line[3] = tol_minus
                    elif not measurement_line[4]:
                        measurement_line[4] = bonus
    return pdf_blocks_text
