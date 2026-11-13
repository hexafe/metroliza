"""Disposable native private-store ownership control; no SIDs or ACLs are emitted."""
from __future__ import annotations

import ctypes
import json
import os
from pathlib import Path
import sys

from metroliza.shared.diagnostic_store import IncidentStore
from scripts.qualify_windows_diagnostics import _WindowsApi, TOKEN_USER
from tests.test_diagnostic_store import _incident


def _owner_is_user(api, path, token):
    wt = api.wintypes
    get_security = api.advapi.GetFileSecurityW
    get_security.argtypes = [wt.LPCWSTR, wt.DWORD, ctypes.c_void_p, wt.DWORD, ctypes.POINTER(wt.DWORD)]
    get_security.restype = wt.BOOL
    required = wt.DWORD()
    get_security(str(path), 1, None, 0, ctypes.byref(required))
    if not 0 < required.value <= 65536:
        raise RuntimeError()
    descriptor = ctypes.create_string_buffer(required.value)
    if not get_security(str(path), 1, descriptor, len(descriptor), ctypes.byref(required)):
        raise RuntimeError()
    get_owner = api.advapi.GetSecurityDescriptorOwner
    get_owner.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wt.BOOL)]
    get_owner.restype = wt.BOOL
    owner, defaulted = ctypes.c_void_p(), wt.BOOL()
    if not get_owner(descriptor, ctypes.byref(owner), ctypes.byref(defaulted)) or not owner:
        raise RuntimeError()
    user = api._token_information(token, TOKEN_USER)
    user_sid = ctypes.cast(user, ctypes.POINTER(api.SID_AND_ATTRIBUTES)).contents.Sid
    api.advapi.EqualSid.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    api.advapi.EqualSid.restype = wt.BOOL
    if not api.advapi.IsValidSid(owner) or not api.advapi.IsValidSid(user_sid):
        raise RuntimeError()
    return bool(api.advapi.EqualSid(owner, user_sid))


def _set_token_owner_user(api, token):
    user = api._token_information(token, TOKEN_USER)
    pointer = ctypes.cast(user, ctypes.POINTER(api.SID_AND_ATTRIBUTES)).contents.Sid
    owner = ctypes.c_void_p(pointer)
    if not api.advapi.SetTokenInformation(token, 4, ctypes.byref(owner), ctypes.sizeof(owner)):
        raise RuntimeError()
    observed = api._token_information(token, 4)
    observed_sid = ctypes.cast(observed, ctypes.POINTER(ctypes.c_void_p)).contents.value
    if not api.advapi.EqualSid(pointer, observed_sid):
        raise RuntimeError()


def main():
    root = Path(sys.argv[1])
    if not root.is_absolute() or not root.is_dir() or root.is_symlink() or any(root.iterdir()):
        return 2
    api = _WindowsApi()
    wt = api.wintypes
    api.advapi.ImpersonateLoggedOnUser.argtypes = [wt.HANDLE]
    api.advapi.ImpersonateLoggedOnUser.restype = wt.BOOL
    api.advapi.RevertToSelf.argtypes = []
    api.advapi.RevertToSelf.restype = wt.BOOL
    result = {"schema_version": 1, "cleanup": True, "control_complete": False}
    token = None
    impersonating = False

    def revert():
        nonlocal impersonating
        if impersonating:
            if not api.advapi.RevertToSelf():
                os._exit(3)
            impersonating = False

    def restricted(action):
        nonlocal impersonating
        if not api.advapi.ImpersonateLoggedOnUser(token):
            raise RuntimeError()
        impersonating = True
        try:
            return action()
        finally:
            revert()

    try:
        token = api._restricted_token()
        result["medium_integrity"] = api._integrity_rid(token) == 0x2000
        admin = ctypes.create_string_buffer(68)
        size = wt.DWORD(len(admin))
        if not api.advapi.CreateWellKnownSid(26, None, admin, ctypes.byref(size)):
            raise RuntimeError()
        result["nonadmin"] = not api._has_effective_admin_membership(token, admin)
        def ancestor_access():
            path = root / "ancestor-control"
            path.mkdir()
            source = path / "fixed"
            source.write_bytes(b"synthetic")
            if source.read_bytes() != b"synthetic":
                raise RuntimeError()
            source.unlink()
            path.rmdir()
            return True

        result["ancestor_accessible"] = restricted(ancestor_access)
        (root / "parent" / "Roaming").mkdir(parents=True)
        roots = [root / name / "Metroliza" / "diagnostics" for name in ("parent", "restricted", "user-owner")]
        incident = _incident()
        stores = [IncidentStore(path) for path in roots]
        result["parent_create"] = stores[0].list_reports().status.value
        result["parent_owner_is_user"] = _owner_is_user(api, roots[0], token)
        result["parent_restricted_publish"] = restricted(lambda: stores[0].publish(incident).status.value)
        result["restricted_create_publish"] = restricted(lambda: stores[1].publish(incident).status.value)
        result["restricted_owner_is_user"] = _owner_is_user(api, roots[1], token)
        result["restricted_host_read"] = stores[1].list_reports().status.value
        result["restricted_full_readback"] = stores[1].load(incident.report_id).incident == incident
        # Reproduce _QualificationRunner exactly: the elevated host creates
        # state/Roaming first; only the sibling private store is initialized
        # under the restricted identity.
        initialized_roaming = root / "initialized" / "Roaming"
        initialized_roaming.mkdir(parents=True)
        initialized = IncidentStore(root / "initialized" / "Metroliza" / "diagnostics")
        if not initialized_roaming.is_dir() or initialized.root.exists():
            raise RuntimeError()
        api.initialize_incident_store(initialized)
        if not initialized_roaming.is_dir():
            raise RuntimeError()
        result["initialized_owner_is_user"] = _owner_is_user(api, initialized.root, token)
        result["initialized_restricted_publish"] = restricted(lambda: initialized.publish(incident).status.value)
        result["initialized_full_readback"] = initialized.load(incident.report_id).incident == incident
        # Only this disposable token's default owner changes. Production ACL and
        # store code are untouched; this third control is not qualification PASS.
        _set_token_owner_user(api, token)
        result["user_owner_create_publish"] = restricted(lambda: stores[2].publish(incident).status.value)
        result["user_owner_is_user"] = _owner_is_user(api, roots[2], token)
        result["user_owner_host_read"] = stores[2].list_reports().status.value
        result["user_owner_full_readback"] = stores[2].load(incident.report_id).incident == incident
        result["control_complete"] = True
    except Exception:
        result["control_complete"] = False
    finally:
        revert()
        if not api._close_handles(token):
            result["cleanup"] = False
    print(json.dumps(result, sort_keys=True))
    return 0 if result["cleanup"] and result["control_complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
