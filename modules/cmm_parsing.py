"""Pure parsing interface for CMM PDF tokenization/block parsing.

Input contract:
    raw_lines: list[str] (equivalent to ``CMMReportParser.pdf_raw_text``)

Output contract:
    list where each item matches legacy ``pdf_blocks_text`` shape:
    [header_comment: list, dimensions: list[list]]
"""

from __future__ import annotations

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
    "D2": 5,
    "D3": 5,
    "D4": 5,
    "A": 7,
}



def _strip_comment_prefix(text: str) -> str:
    """Strip leading CMM comment markers without regex overhead."""
    if not text or text[0] not in "#*/":
        return text.strip()

    idx = 0
    while idx < len(text) and text[idx] in "#*/":
        idx += 1
    return text[idx:].strip()


def _drop_trailing_empty_blocks(pdf_blocks_text: list[list[Any]]) -> None:
    """Remove terminal cleanup blocks that carry no useful measurement rows."""

    def _is_disposable_terminal_block(block: list[Any]) -> bool:
        if len(block) <= 1 or block[1]:
            return False

        header_tokens: list[str] = []
        for header_entry in block[0]:
            if isinstance(header_entry, str):
                header_tokens.append(header_entry)
            elif isinstance(header_entry, list):
                header_tokens.extend(str(item) for item in header_entry if isinstance(item, str))

        normalized_header = " ".join(token.strip() for token in header_tokens if token.strip()).upper()
        return not normalized_header or normalized_header.startswith("END")

    while pdf_blocks_text and _is_disposable_terminal_block(pdf_blocks_text[-1]):
        pdf_blocks_text.pop()

def parse_raw_lines_to_blocks(raw_lines: list[str]) -> list[list[Any]]:
    """Parse raw report lines into legacy block structure."""
    split_lines = [line.split() for line in raw_lines]

    def is_comment_or_header(line: str) -> bool:
        return line.startswith(("#", "*"))

    def is_dim_line(line: str) -> bool:
        return line.startswith("DIM")

    def parse_numeric_token(value: str) -> float | None:
        try:
            return float(value)
        except ValueError:
            return None

    def process_line(line: list[Any]) -> list[Any]:
        processed_line: list[Any] = []
        code = line[0] if line else ""

        def process_tp_line(tokens: list[Any]) -> list[Any]:
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

            has_tp_qualifier = False
            has_explicit_nom_label = False

            numeric_values: list[float] = []
            for token in tokens[1:]:
                if isinstance(token, float):
                    numeric_values.append(token)
                    continue

                normalized_token = str(token).upper().rstrip(":")
                if normalized_token in tp_qualifiers:
                    has_tp_qualifier = True
                    continue
                elif normalized_token in semantic_labels:
                    if normalized_token == "NOM":
                        has_explicit_nom_label = True
                    continue

            if len(numeric_values) < 5:
                return []

            nom = 0.0
            # Qualified TP rows frequently omit NOM and start directly with +TOL.
            # In that shape we must not reinterpret an extra trailing numeric token
            # (OCR spill-over / inherited row noise) as NOM.
            if len(numeric_values) >= 6 and (has_explicit_nom_label or not has_tp_qualifier):
                nom, tol_plus, bonus, meas, dev, outtol = numeric_values[:6]
            else:
                tol_plus, bonus, meas, dev, outtol = numeric_values[:5]

            return ["TP", nom, tol_plus, "", bonus, meas, dev, outtol]

        if str(code).startswith("TP"):
            processed_line = process_tp_line(line)
            return processed_line

        numeric_values = line[1:]

        if code in ["X", "Y", "Z"] and len(numeric_values) == 3:
            processed_line = [code, numeric_values[0], "", "", "", numeric_values[1], numeric_values[2], ""]
        elif code in ["X", "Y", "Z"] and len(numeric_values) == 6:
            processed_line = [
                code,
                numeric_values[0],
                numeric_values[1],
                numeric_values[2],
                "",
                numeric_values[3],
                numeric_values[4],
                numeric_values[5],
            ]
        elif code == "M" and len(numeric_values) == 6:
            processed_line = [
                code,
                numeric_values[0],
                numeric_values[1],
                numeric_values[2],
                "",
                numeric_values[3],
                numeric_values[4],
                numeric_values[5],
            ]
        elif code == "M" and len(numeric_values) == 7:
            processed_line = [
                code,
                numeric_values[0],
                numeric_values[1],
                numeric_values[2],
                numeric_values[3],
                numeric_values[4],
                numeric_values[5],
                numeric_values[6],
            ]
        elif code == "D" and len(numeric_values) == 6:
            processed_line = [
                code,
                numeric_values[0],
                numeric_values[1],
                numeric_values[2],
                "",
                numeric_values[3],
                numeric_values[4],
                numeric_values[5],
            ]
        elif code == "RN" and len(numeric_values) == 6:
            processed_line = [
                code,
                numeric_values[0],
                numeric_values[1],
                numeric_values[2],
                "",
                numeric_values[3],
                numeric_values[4],
                numeric_values[5],
            ]
        elif code == "DF" and len(numeric_values) == 7:
            processed_line = [
                code,
                numeric_values[0],
                numeric_values[1],
                numeric_values[2],
                numeric_values[3],
                numeric_values[4],
                numeric_values[5],
                numeric_values[6],
            ]
        elif code == "DF" and len(numeric_values) == 6:
            processed_line = [
                code,
                numeric_values[0],
                numeric_values[1],
                numeric_values[2],
                "0",
                numeric_values[3],
                numeric_values[4],
                numeric_values[5],
            ]
        elif code == "PR" and len(numeric_values) == 6:
            processed_line = [
                code,
                numeric_values[0],
                numeric_values[1],
                numeric_values[2],
                "",
                numeric_values[3],
                numeric_values[4],
                numeric_values[5],
            ]
        elif code == "PR" and len(numeric_values) == 3:
            processed_line = [code, numeric_values[0], "", "", "", numeric_values[1], numeric_values[2], ""]
        elif code == "PA" and len(numeric_values) == 3:
            processed_line = [code, numeric_values[0], "", "", "", numeric_values[1], numeric_values[2], ""]
        elif code in {"D1", "D2", "D3", "D4"} and len(numeric_values) == 4:
            processed_line = [code, numeric_values[0], numeric_values[1], numeric_values[2], "", numeric_values[3], "", ""]
        elif code == "A" and len(numeric_values) == 6:
            processed_line = [
                code,
                numeric_values[0],
                numeric_values[1],
                numeric_values[2],
                "0",
                numeric_values[3],
                numeric_values[4],
                numeric_values[5],
            ]
        return processed_line

    def extract_measurement_tokens_and_raw_lines_consumed(
        start_index: int, preserve_non_numeric_tokens: bool = False
    ) -> tuple[list[Any], int]:
        if start_index >= len(raw_lines):
            return [], 0

        code_tokens = split_lines[start_index]
        if not code_tokens:
            return [], 0

        code, *first_line_tokens = code_tokens
        parsed_tokens: list[Any] = [code]
        numeric_token_count = 0
        raw_lines_consumed = 1
        max_token_count = MEASUREMENT_LINE_MAP.get(code, 0)
        max_numeric_count = max(max_token_count - 1, 0) if max_token_count else 0

        def append_tokens(tokens: list[str]) -> None:
            nonlocal numeric_token_count
            for token in tokens:
                numeric_token = parse_numeric_token(token)
                if numeric_token is not None:
                    parsed_tokens.append(numeric_token)
                    numeric_token_count += 1
                    if max_numeric_count and numeric_token_count >= max_numeric_count:
                        break
                elif preserve_non_numeric_tokens:
                    parsed_tokens.append(token)
                    if max_numeric_count and numeric_token_count >= max_numeric_count:
                        break

        append_tokens(first_line_tokens)

        for follow_index in range(start_index + 1, len(raw_lines)):
            if max_numeric_count and numeric_token_count >= max_numeric_count:
                break

            raw_line = raw_lines[follow_index]
            raw_line_tokens = split_lines[follow_index]
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

        line_tokens = split_lines[index]
        if not is_comment_or_header(line) and len(line_tokens) == 3:
            continue

        if text_block:
            if is_comment_or_header(line) or is_dim_line(line):
                if is_comment_or_header(line) and prev_line is not None and is_comment_or_header(prev_line):
                    formatted_line = _strip_comment_prefix(line)
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
                    formatted_line = _strip_comment_prefix(line)
                    header_comment.append([formatted_line])
                    text_block.append(header_comment)

            else:
                tokens = line_tokens
                if tokens and tokens[0] in MEASUREMENT_LINE_MAP:
                    preserve_non_numeric_tokens = tokens[0].startswith("TP")
                    parsed_tokens, raw_lines_consumed = extract_measurement_tokens_and_raw_lines_consumed(
                        index,
                        preserve_non_numeric_tokens=preserve_non_numeric_tokens,
                    )

                    raw_lines_to_skip = max(raw_lines_consumed - 1, 0)
                    temp_line = process_line(parsed_tokens)
                    if temp_line:
                        dim_block.append(temp_line)
        else:
            if not pdf_blocks_text:
                if is_comment_or_header(line):
                    formatted_line = _strip_comment_prefix(line)
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
                    formatted_line = _strip_comment_prefix(line)
                    header_comment.append([formatted_line])

    if text_block:
        candidate_block = [header_comment] + [dim_block]
        if not pdf_blocks_text or pdf_blocks_text[-1] != candidate_block:
            pdf_blocks_text.append(candidate_block)

    add_tolerances_to_blocks(pdf_blocks_text)
    _drop_trailing_empty_blocks(pdf_blocks_text)
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
