"""Disposable native control. Emits only fixed synthetic outcomes, never SIDs/ACLs."""
import ctypes
import json
import os

from scripts.qualify_windows_diagnostics import _WindowsApi


class UnrepairedTokenApi(_WindowsApi):
    def _set_private_default_dacl(self, token):
        pass


def main():
    api = UnrepairedTokenApi()
    wt = api.wintypes

    class SecurityDescriptor(ctypes.Structure):
        _fields_ = [
            ("Revision", wt.BYTE), ("Sbz1", wt.BYTE), ("Control", wt.WORD),
            ("Owner", ctypes.c_void_p), ("Group", ctypes.c_void_p),
            ("Sacl", ctypes.c_void_p), ("Dacl", ctypes.c_void_p),
        ]

    class SecurityAttributes(ctypes.Structure):
        _fields_ = [("length", wt.DWORD), ("descriptor", ctypes.c_void_p), ("inherit", wt.BOOL)]

    api.advapi.ImpersonateLoggedOnUser.argtypes = [wt.HANDLE]
    api.advapi.ImpersonateLoggedOnUser.restype = wt.BOOL
    api.advapi.RevertToSelf.argtypes = []
    api.advapi.RevertToSelf.restype = wt.BOOL
    api.advapi.InitializeSecurityDescriptor.argtypes = [ctypes.c_void_p, wt.DWORD]
    api.advapi.InitializeSecurityDescriptor.restype = wt.BOOL
    api.advapi.SetSecurityDescriptorDacl.argtypes = [ctypes.c_void_p, wt.BOOL, ctypes.c_void_p, wt.BOOL]
    api.advapi.SetSecurityDescriptorDacl.restype = wt.BOOL
    api.kernel.CreatePipe.argtypes = [ctypes.POINTER(wt.HANDLE), ctypes.POINTER(wt.HANDLE), ctypes.c_void_p, wt.DWORD]
    api.kernel.CreatePipe.restype = wt.BOOL
    result = {
        "default_before": "not_run", "explicit_private": False,
        "default_after": False, "medium_integrity": False, "nonadmin": False,
        "cleanup": True,
    }
    token = None
    impersonating = False

    def revert():
        nonlocal impersonating
        if impersonating:
            if not api.advapi.RevertToSelf():
                os._exit(3)
            impersonating = False

    def impersonate():
        nonlocal impersonating
        if not api.advapi.ImpersonateLoggedOnUser(token):
            raise RuntimeError()
        impersonating = True

    def pipe(attributes):
        read, write = wt.HANDLE(), wt.HANDLE()
        try:
            ctypes.set_last_error(0)
            success = bool(api.kernel.CreatePipe(ctypes.byref(read), ctypes.byref(write), attributes, 0))
            error = ctypes.get_last_error()
            return "passed" if success else "access_denied" if error == 5 else "other"
        finally:
            if not api._close_handles(read, write):
                result["cleanup"] = False

    try:
        token = api._restricted_token()
        acl = api._private_default_acl(token)
        descriptor = SecurityDescriptor()
        if (not api.advapi.InitializeSecurityDescriptor(ctypes.byref(descriptor), 1)
                or not api.advapi.SetSecurityDescriptorDacl(ctypes.byref(descriptor), True, acl, False)
                or not descriptor.Dacl):
            raise RuntimeError()
        attributes = SecurityAttributes(ctypes.sizeof(SecurityAttributes), ctypes.addressof(descriptor), False)
        impersonate()
        # Same unmodified token: only explicit object security differs.
        result["default_before"] = pipe(None)
        result["explicit_private"] = pipe(ctypes.byref(attributes)) == "passed"
        revert()
        _WindowsApi._set_private_default_dacl(api, token)
        impersonate()
        result["default_after"] = pipe(None) == "passed"
        revert()
        result["medium_integrity"] = api._integrity_rid(token) == 0x2000
        admin = ctypes.create_string_buffer(68)
        size = wt.DWORD(len(admin))
        if not api.advapi.CreateWellKnownSid(26, None, admin, ctypes.byref(size)):
            raise RuntimeError()
        result["nonadmin"] = not api._has_effective_admin_membership(token, admin)
    except Exception:
        result["cleanup"] = False
    finally:
        revert()
        if not api._close_handles(token):
            result["cleanup"] = False
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
