# Historical Metroliza test build 261021 archive

Source commit `a0d37690272f6d0b05263076b20cc1b0cfe84780`. Product base `a58b693f65f81a6a7b2d3ad368eb78522754e6f8`.
Original Actions run [39545859603](https://github.com/hexafe/metroliza/actions/runs/39545859603).
Original test-build ZIPs, exact archive/member hashes, raw sidecar receipts and the actual
embedded `build_provenance.json` are retained. No standalone `BUILD_INFO.txt` exists in the
launcher payload; none is invented or claimed as archived. The payload manifest hash and
the embedded provenance hash were verified by read-only parsing; no EXE was executed.

Keep this archival container unpublished. It has no release-owner Go, does not identify the
final RC build and does not qualify STEP3 or packaged Windows acceptance. The old build-number
commit is retained here and is not merged into final RC metadata.

Repository-readable receipt copies normalize CRLF to LF; `readable-copy-manifest.json` records
original and derived hashes. Original ZIPs and raw sidecar assets remain byte-exact externally.
This README is archive documentation authored under #1153, not an original build artifact.

The launcher payload contains 2156 files. Exact executable hashes, source commit, build label,
packager and Python version are retained in provenance. The GitHub archive also stores the
self-contained original47-ref bundle; downloading it into a fresh empty repository recovered
47/47 exact commit/tree pairs with no alternates and fsck exit 0.

The PO selected GitHub as the external recovery source for this cleanup: “zabezpiecz wymagane
commity i historyczne buildy trwałymi referencjami na GitHub” and “sprawdź odzyskanie dokładnego
commit/tree z tego zewnętrznego źródła w czystym repo”. The original local bundle is also retained.
GitHub tags and the bundle asset share the repository/account failure domain; no separate-provider
backup or tag immutability is claimed. Owner: hexafe repository maintainer.
