# Synthetic protocol fixtures

These are byte-preserved fixtures from #1047 preparation, used only by acceptance
driver regression tests. They are not evidence that the current source or an EXE
is qualified.

- `core-source-engineering-receipt.json` is a historical source-only receipt. The
  protocol must reject it as packaged Windows evidence.
- `w05-numeric-source-tabular.json` is the recorded public-CSV result used to test
  rejection of incorrect row IDs, rounded integers, changed types and hashes.
- `literal-measurement-labels.xlsx` is the synthetic literal-label workbook used
  for verifier/copy protocol controls. The actual executable scenario must create
  its own fresh workbook.

The immutable public input PDFs and CSVs are in the adjacent
`windows_candidate` fixture directory. Their seven hashes are enforced by the
driver and application scenario.
