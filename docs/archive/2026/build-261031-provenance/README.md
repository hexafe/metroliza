# 2026.09 RC1 build 261031 candidate archive

Source commit `6dc0554667a842e107bd547fc86aeefedc52aec4`, tree `710332799cb9d7b6f58e59603b8e4630fb2f34d0`.
Actions run [41154237127](https://github.com/hexafe/metroliza/actions/runs/41154237127): Combined job
124397401592 and downloaded-ZIP job 124401380755 PASS (#1158). Archive tag `archive/2026.09-rc1/build-261031`
(annotated, on the source commit) and an unpublished draft release with the same tag name hold the
original bytes. `github-archive.json` records every asset digest and the recovery check.

Keep the draft unpublished. It is not a release, has no legal sign-off or release-owner Go, and manual
Windows acceptance (E1–E14) was NOT_RUN when it was made. Actions retention of the originals ends 2027-01-29.

Tester download (the user ZIP itself, stored unchanged):
[`metroliza_2026.09rc1_261031_windows.zip`](https://github.com/hexafe/metroliza/releases/download/untagged-e800cc5baa028c387acb/metroliza_2026.09rc1_261031_windows.zip).
The link works only for accounts with write access to the repository, and only while the release stays a draft;
otherwise use the Actions artifact named in the tester packet.

| Layer | Archived asset | SHA-256 | Bytes |
|---|---|---|---|
| Actions archive of artifact 13024584128 | `13024584128-windows-release-zip.zip` | `987009e3e9ea53499f83172ada27218056b4882b0a000924116385eb78795ef2` | 284425199 |
| User ZIP (its only member; also stored directly) | `metroliza_2026.09rc1_261031_windows.zip` | `7005d05e13ea9159bcc7ec6b10de6224ff7fb4f19d0b11162f8ed92552699c20` | 284555192 |
| Launcher EXE (member of the user ZIP, unsigned) | `metroliza_2026.09rc1_261031_launcher.exe` | `2ee40bd389f9547cf9a0f52294d4c8943e2c509c184f91c6c09957cc2c778952` | 334822568 |
| Actions archive of artifact 13024638914 | `13024638914-windows-candidate-development-onedir.zip` | `818c1cbbe81211fec39bfb83ffcb75c9d97742007037b4730ed5ec1efadfa5f5` | 269883409 |
| Accepted onedir archive (its only member) | `qualified-windows-development-package.zip` | `799760d31bbfa2c5c6f59e05bc09b7e2d79829537eb2b004613179569dd49485` | 538758644 |
| Actions archive of artifact 13024514239 | `13024514239-windows-candidate-acceptance-receipts.zip` | `ea0580b807a2c2bd1ac5eaa5b76aa8b7263fc977058a625db695303f42ae59d4` | 555823 |
| Actions archive of artifact 13024459473 | `13024459473-windows-release-zip-download-receipt.zip` | `ab52095f6ea2256e26c090080833447c0f10dd6afb803ccae59eddd3aeb4e026` | 696 |

The outer Actions archive hashes equal the artifact `digest` reported by the GitHub API. Two tree-level values
are not file hashes: the payload content SHA-256 `6b8ce7372494c77def5005dd456bd68bc77828239bbf4d23fe63508fa0a56ae1`
(launcher packer definition, `scripts/release_zip.py onedir-hash`, 2174 files; runtime cache
`2026.09rc1_261031-6b8ce7372494_6dc05546`) and the Combined `package_tree_sha256`
`1461ef3a7038a58f2a70ce9e98ed48df64ab67497d57fd5a03428992359986a9`.

The draft also holds `README.md` (readable manifest), `ARCHIVE_MANIFEST.json` (machine-readable manifest with
the location of every receipt inside the archives), `ARCHIVE_SHA256SUMS`, `combined-candidate-receipt.json`,
the byte-exact payload manifest read from the EXE trailer (`launcher-payload-manifest.json`), the local
`release_zip.py verify` receipt, raw logs of jobs 124397401592 and 124401380755, and the run, job and artifact
metadata. Provenance, the ZIP gate receipt, the inventory gate receipt and the shipped inventory stay inside
the original archives; the manifests name their paths.

Recovery check 2026-10-31: all 16 assets downloaded into a fresh empty directory; `ARCHIVE_SHA256SUMS` 15/15 OK;
16/16 GitHub digests and sizes equal the downloaded bytes. The user ZIP re-extracted from its Actions archive is
byte-identical to the stored asset; the EXE and onedir archive reproduce the hashes and sizes above; the five
receipt hashes named in the Combined receipt match. `release_zip.py verify` from the recovered tag, with the
expected source, content and EXE SHA: PASS. `onedir-hash` of the recovered onedir gives `6b8ce737…`, and its
2174 path, size and SHA-256 records are identical to the EXE payload manifest. The tag fetched into a fresh
repository gives the exact commit and tree; `git fsck --full` exit 0.

These checks are static (the EXE was not executed here). Combined, launcher smoke and the ZIP gates ran in CI;
manual acceptance is tracked in [the tester ZIP packet](../../../release_checks/rc1_261031_zip_acceptance_2026-10-31.md).

The tag and draft share the repository/account failure domain. A local copy is kept by the maintainer;
no separate-provider backup or tag immutability is claimed. Owner: hexafe repository maintainer.
Build 261029 and [its archive](../build-261029-provenance/README.md) are historical and unchanged.
