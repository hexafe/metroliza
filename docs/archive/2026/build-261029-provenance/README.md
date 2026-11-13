# 2026.09 RC1 build 261029 accepted candidate archive

Source commit `b2510e0aa651e8c96363e5a9c224c841318cc9d0`, tree `e165267b09b437b7fe5a1556b5809e87123f1c9a`.
Actions run [40991278786](https://github.com/hexafe/metroliza/actions/runs/40991278786); Combined Windows
candidate acceptance PASS in job 123854028888 (#1158). Archive tag `archive/2026.09-rc1/build-261029`
(annotated, on the source commit) and an unpublished draft release with the same tag name hold the
original bytes. `github-archive.json` records every asset digest and the recovery check.

Keep the draft unpublished. It is not a release, has no release-owner Go and does not extend the
Combined acceptance to other bytes. Actions retention of the originals ends 2027-01-28.

| Layer | Archived asset | SHA-256 | Bytes |
|---|---|---|---|
| Actions archive of artifact 12949329678 | `12949329678-windows-candidate-development-onedir.zip` | `4e7ce99fccf99ab97034cd5e8e3a69118cfd75b34c243c51d5bdb5b4905ce9ce` | 269888624 |
| Accepted onedir ZIP (its member) | `qualified-windows-development-package.zip` | `da8a25eb2d0a4e79c80823bc03f470bc81fde3fe0a83d7037437ac61e495b84c` | 538738623 |
| Actions archive of artifact 12949892358 | `12949892358-windows-supervised-launcher-exe.zip` | `f16601e3bfc4ec4bbf23bc53fe531d0bd156a650c94a09150b4bae6f1b81d86c` | 288770271 |
| Tester launcher EXE (its member, also stored directly) | `metroliza_2026.09rc1_261029_launcher.exe` | `16f3edb988bc9d0e5000c89796f40daf0bd2ebfef468c6e34827a3947512b408` | 334830360 |
| Actions archive of artifact 12950335316 | `12950335316-windows-candidate-acceptance-receipts.zip` | `3c431ae7efc3ca8779e8a2b09be10d977ecc5c9db2c568b2a0776423ff7ae11f` | 548573 |

The outer Actions archive hashes equal the artifact `digest` reported by the GitHub API. The draft also
holds the launcher provenance sidecar, `combined-candidate-receipt.json`, the companion package identity,
compute worker and synthetic launcher qualification archives, raw logs of jobs 123854028888, 123854029137
and 123854029037, the launcher payload manifest and the embedded `build_provenance.json` read from it.

Recovery check 2026-10-30: a download into a fresh empty directory matched `ARCHIVE_SHA256SUMS` and the
GitHub digests; re-extraction reproduced the inner ZIP and EXE hashes and the four core receipt hashes
named in the combined receipt; the tag fetched into a fresh repository gave the exact commit and tree.

The EXE is a separate build in job 123854029137 of the same run and source; Combined did not run it.
Read-only payload parsing (no execution) verified all 2174 blobs against manifest
`99576585d7cc8a6386f74322ab37538ffab73e446ec5cf96c75e850d8a9ed4e5`. It contains no `BUILD_INFO.txt`.
Manual acceptance of the EXE is tracked in
[the acceptance packet](../../../release_checks/rc1_261029_exe_acceptance_2026-10-30.md).

The tag and draft share the repository/account failure domain. A local copy is kept by the maintainer;
no separate-provider backup or tag immutability is claimed. Owner: hexafe repository maintainer.
