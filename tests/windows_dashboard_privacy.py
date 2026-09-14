"""Native Windows privacy oracle for owned realtime-dashboard test fixtures.

The public receipt deliberately contains no account names, SID strings, descriptor
contents, or filesystem paths.  It is Windows-only; POSIX coverage retains the
existing ``0700`` assertion in the caller.
"""

from __future__ import annotations

import ctypes
from contextlib import contextmanager
from dataclasses import asdict, dataclass
import os
from pathlib import Path
import secrets
from ctypes import wintypes


_OWNER_SECURITY_INFORMATION = 0x00000001
_GROUP_SECURITY_INFORMATION = 0x00000002
_DACL_SECURITY_INFORMATION = 0x00000004
_UNPROTECTED_DACL_SECURITY_INFORMATION = 0x20000000
_PROTECTED_DACL_SECURITY_INFORMATION = 0x80000000
_SE_FILE_OBJECT = 1

_TOKEN_QUERY = 0x0008
_TOKEN_DUPLICATE = 0x0002
_TOKEN_IMPERSONATE = 0x0004
_TOKEN_USER = 1
_TOKEN_GROUPS = 2
_TOKEN_PRIVILEGES = 3
_TOKEN_OWNER = 4
_SECURITY_IMPERSONATION = 2
_TOKEN_IMPERSONATION = 2
_DISABLE_MAX_PRIVILEGE = 0x00000001

_WIN_WORLD_SID = 1
_WIN_AUTHENTICATED_USER_SID = 17
_WIN_BUILTIN_ADMINISTRATORS_SID = 26
_WIN_BUILTIN_USERS_SID = 27
_WIN_LOCAL_SYSTEM_SID = 22

_ACL_REVISION = 2
_ACCESS_ALLOWED_ACE_TYPE = 0
_INHERITED_ACE = 0x10
_INHERIT_ONLY_ACE = 0x08
_OBJECT_INHERIT_ACE = 0x01
_CONTAINER_INHERIT_ACE = 0x02
_GENERIC_READ = 0x80000000
_GENERIC_WRITE = 0x40000000
_GENERIC_EXECUTE = 0x20000000
_GENERIC_ALL = 0x10000000
_FILE_GENERIC_READ = 0x00120089
_FILE_GENERIC_WRITE = 0x00120116
_DELETE = 0x00010000
_WRITE_DAC = 0x00040000
_WRITE_OWNER = 0x00080000
_FILE_READ_DATA = 0x0001
_FILE_WRITE_DATA = 0x0002
_FILE_APPEND_DATA = 0x0004
_FILE_LIST_DIRECTORY = _FILE_READ_DATA
_FILE_ADD_FILE = _FILE_WRITE_DATA
_FILE_DELETE_CHILD = 0x0040
_FILE_GENERIC_EXECUTE = 0x001200A0
_FILE_ALL_ACCESS = 0x001F01FF
_ACL_SIZE_INFORMATION = 2
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
_SE_DACL_PROTECTED = 0x1000
_SE_GROUP_ENABLED = 0x00000004
_SE_GROUP_USE_FOR_DENY_ONLY = 0x00000010
_SE_PRIVILEGE_ENABLED = 0x00000002
_ACCESS_ALLOWED_OBJECT_ACE_TYPE = 5
_ACCESS_ALLOWED_COMPOUND_ACE_TYPE = 4
_ACCESS_ALLOWED_CALLBACK_ACE_TYPE = 9
_ACCESS_ALLOWED_CALLBACK_OBJECT_ACE_TYPE = 11


class _SID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", wintypes.DWORD)]


class _TOKEN_USER_STRUCT(ctypes.Structure):
    _fields_ = [("User", _SID_AND_ATTRIBUTES)]


class _TOKEN_OWNER_STRUCT(ctypes.Structure):
    _fields_ = [("Owner", ctypes.c_void_p)]


class _TOKEN_GROUPS_LAYOUT(ctypes.Structure):
    _fields_ = [("GroupCount", wintypes.DWORD), ("Groups", _SID_AND_ATTRIBUTES * 1)]


class _LUID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG), ("Attributes", wintypes.DWORD)]


class _LUID(ctypes.Structure):
    _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]


class _TOKEN_PRIVILEGES_LAYOUT(ctypes.Structure):
    _fields_ = [("PrivilegeCount", wintypes.DWORD), ("Privileges", _LUID_AND_ATTRIBUTES * 1)]


class _ACL_SIZE_INFORMATION_STRUCT(ctypes.Structure):
    _fields_ = [
        ("AceCount", wintypes.DWORD),
        ("AclBytesInUse", wintypes.DWORD),
        ("AclBytesFree", wintypes.DWORD),
    ]


class _GENERIC_MAPPING(ctypes.Structure):
    _fields_ = [
        ("GenericRead", wintypes.DWORD),
        ("GenericWrite", wintypes.DWORD),
        ("GenericExecute", wintypes.DWORD),
        ("GenericAll", wintypes.DWORD),
    ]


class _ACE_HEADER(ctypes.Structure):
    _fields_ = [("AceType", ctypes.c_ubyte), ("AceFlags", ctypes.c_ubyte), ("AceSize", ctypes.c_ushort)]


@dataclass(frozen=True)
class DashboardPrivacyReceipt:
    """Safe native facts from the private-directory oracle."""

    ordinary_access_context: str
    directory_owner_class: str
    html_owner_class: str
    directory_owner_matches_current: bool
    html_owner_matches_current: bool
    directory_dacl_present: bool
    html_dacl_present: bool
    directory_allowed_ace_count: int
    html_allowed_ace_count: int
    directory_broad_allow_count: int
    html_broad_allow_count: int
    directory_inherited_broad_allow_count: int
    html_inherited_broad_allow_count: int
    directory_broad_content_denied: bool
    html_broad_content_denied: bool
    restricted_access_check_read: bool
    restricted_access_check_write: bool
    restricted_access_check_delete: bool
    restricted_token_read: bool
    restricted_token_write: bool
    restricted_token_delete: bool

    def as_dict(self) -> dict[str, bool | int | str]:
        """Return only JSON-safe, non-identifying values for CI receipts."""
        return asdict(self)


@dataclass(frozen=True)
class _DescriptorFacts:
    allowed_ace_count: int
    broad_allow_count: int
    inherited_broad_allow_count: int
    has_untrusted_allow: bool
    owner_class: str


def _require_windows() -> None:
    if os.name != "nt":
        raise AssertionError("privacy_oracle_requires_windows")


def _win_error(stage: str) -> AssertionError:
    return AssertionError(f"privacy_oracle_{stage}_failed")


def _api():
    _require_windows()
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    kernel.GetCurrentProcess.argtypes = []
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    advapi.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    advapi.OpenProcessToken.restype = wintypes.BOOL
    advapi.GetTokenInformation.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    advapi.GetTokenInformation.restype = wintypes.BOOL
    advapi.CreateWellKnownSid.argtypes = [wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD)]
    advapi.CreateWellKnownSid.restype = wintypes.BOOL
    advapi.LookupPrivilegeValueW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.POINTER(_LUID)]
    advapi.LookupPrivilegeValueW.restype = wintypes.BOOL
    advapi.EqualSid.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    advapi.EqualSid.restype = wintypes.BOOL
    advapi.CreateRestrictedToken.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(_SID_AND_ATTRIBUTES), wintypes.DWORD,
        ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_SID_AND_ATTRIBUTES), ctypes.POINTER(wintypes.HANDLE),
    ]
    advapi.CreateRestrictedToken.restype = wintypes.BOOL
    advapi.DuplicateTokenEx.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE),
    ]
    advapi.DuplicateTokenEx.restype = wintypes.BOOL
    advapi.ImpersonateLoggedOnUser.argtypes = [wintypes.HANDLE]
    advapi.ImpersonateLoggedOnUser.restype = wintypes.BOOL
    advapi.RevertToSelf.argtypes = []
    advapi.RevertToSelf.restype = wintypes.BOOL
    advapi.MapGenericMask.argtypes = [ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(_GENERIC_MAPPING)]
    advapi.AccessCheck.argtypes = [
        ctypes.c_void_p, wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(_GENERIC_MAPPING), ctypes.c_void_p,
        ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.BOOL),
    ]
    advapi.AccessCheck.restype = wintypes.BOOL
    advapi.GetNamedSecurityInfoW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p),
    ]
    advapi.GetNamedSecurityInfoW.restype = wintypes.DWORD
    advapi.SetNamedSecurityInfoW.argtypes = [
        wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
    ]
    advapi.SetNamedSecurityInfoW.restype = wintypes.DWORD
    advapi.SetFileSecurityW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p]
    advapi.SetFileSecurityW.restype = wintypes.BOOL
    advapi.GetSecurityDescriptorControl.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.WORD), ctypes.POINTER(wintypes.DWORD)]
    advapi.GetSecurityDescriptorControl.restype = wintypes.BOOL
    advapi.GetAclInformation.argtypes = [ctypes.c_void_p, ctypes.POINTER(_ACL_SIZE_INFORMATION_STRUCT), wintypes.DWORD, wintypes.DWORD]
    advapi.GetAclInformation.restype = wintypes.BOOL
    advapi.GetAce.argtypes = [ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p)]
    advapi.GetAce.restype = wintypes.BOOL
    advapi.InitializeAcl.argtypes = [ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD]
    advapi.InitializeAcl.restype = wintypes.BOOL
    advapi.AddAccessAllowedAceEx.argtypes = [ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
    advapi.AddAccessAllowedAceEx.restype = wintypes.BOOL
    advapi.GetLengthSid.argtypes = [ctypes.c_void_p]
    advapi.GetLengthSid.restype = wintypes.DWORD
    return kernel, advapi


def _close(kernel, handle) -> None:
    value = handle.value if hasattr(handle, "value") else handle
    if value and value != _INVALID_HANDLE_VALUE:
        kernel.CloseHandle(handle)


def _token_information(advapi, token, information_class: int):
    needed = wintypes.DWORD()
    advapi.GetTokenInformation(token, information_class, None, 0, ctypes.byref(needed))
    if not needed.value:
        raise _win_error("token_information")
    buffer = ctypes.create_string_buffer(needed.value)
    if not advapi.GetTokenInformation(token, information_class, buffer, needed, ctypes.byref(needed)):
        raise _win_error("token_information")
    return buffer


def _current_token(kernel, advapi):
    token = wintypes.HANDLE()
    if not advapi.OpenProcessToken(
        kernel.GetCurrentProcess(), _TOKEN_QUERY | _TOKEN_DUPLICATE | _TOKEN_IMPERSONATE, ctypes.byref(token)
    ):
        raise _win_error("open_current_token")
    return token


def _well_known_sid(advapi, kind: int):
    needed = wintypes.DWORD()
    advapi.CreateWellKnownSid(kind, None, None, ctypes.byref(needed))
    if not needed.value:
        raise _win_error("well_known_sid")
    buffer = ctypes.create_string_buffer(needed.value)
    if not advapi.CreateWellKnownSid(kind, None, buffer, ctypes.byref(needed)):
        raise _win_error("well_known_sid")
    return buffer


def _same_sid(advapi, left, right) -> bool:
    return bool(advapi.EqualSid(left, right))


def _security_descriptor(advapi, path: Path):
    owner = ctypes.c_void_p()
    group = ctypes.c_void_p()
    dacl = ctypes.c_void_p()
    descriptor = ctypes.c_void_p()
    result = advapi.GetNamedSecurityInfoW(
        str(path),
        _SE_FILE_OBJECT,
        _OWNER_SECURITY_INFORMATION | _GROUP_SECURITY_INFORMATION | _DACL_SECURITY_INFORMATION,
        ctypes.byref(owner),
        ctypes.byref(group),
        ctypes.byref(dacl),
        None,
        ctypes.byref(descriptor),
    )
    if result:
        raise _win_error("get_named_security_info")
    return owner, group, dacl, descriptor


def _assert_fixture_owned_by_current_token(kernel, advapi, owner) -> None:
    token = _current_token(kernel, advapi)
    try:
        current_user = _token_information(advapi, token, _TOKEN_USER)
        current_sid = ctypes.cast(current_user, ctypes.POINTER(_TOKEN_USER_STRUCT)).contents.User.Sid
        current_owner = _token_information(advapi, token, _TOKEN_OWNER)
        owner_sid = ctypes.cast(current_owner, ctypes.POINTER(_TOKEN_OWNER_STRUCT)).contents.Owner
        if not owner or not (_same_sid(advapi, owner, current_sid) or _same_sid(advapi, owner, owner_sid)):
            raise AssertionError("privacy_oracle_fixture_owner_not_current")
    finally:
        _close(kernel, token)


def _original_dacl_security_information(advapi, descriptor) -> int:
    control = wintypes.WORD()
    revision = wintypes.DWORD()
    if not advapi.GetSecurityDescriptorControl(descriptor, ctypes.byref(control), ctypes.byref(revision)):
        raise _win_error("get_fixture_descriptor_control")
    return _DACL_SECURITY_INFORMATION | (
        _PROTECTED_DACL_SECURITY_INFORMATION if control.value & _SE_DACL_PROTECTED else _UNPROTECTED_DACL_SECURITY_INFORMATION
    )


def _ace_grants_content(mask: int) -> bool:
    return bool(
        mask & (_GENERIC_READ | _GENERIC_WRITE | _GENERIC_ALL | _FILE_GENERIC_READ | _FILE_GENERIC_WRITE | _DELETE | _WRITE_DAC | _WRITE_OWNER)
    )


def _owner_class(advapi, owner, current_sid, system_sid, administrators_sid) -> str:
    if not owner:
        raise AssertionError("privacy_oracle_owner_missing")
    for sid, label in (
        (current_sid, "current_user"),
        (system_sid, "system"),
        (administrators_sid, "administrators"),
    ):
        if _same_sid(advapi, owner, sid):
            return label
    raise AssertionError("privacy_oracle_owner_untrusted")


def _inspect_descriptor(advapi, owner, dacl, current_sid, allowed_sids, broad_sids, system_sid, administrators_sid) -> _DescriptorFacts:
    owner_class = _owner_class(advapi, owner, current_sid, system_sid, administrators_sid)
    if not dacl:
        raise AssertionError("privacy_oracle_null_dacl")
    info = _ACL_SIZE_INFORMATION_STRUCT()
    if not advapi.GetAclInformation(dacl, ctypes.byref(info), ctypes.sizeof(info), _ACL_SIZE_INFORMATION):
        raise _win_error("acl_information")
    allowed = broad = inherited_broad = 0
    untrusted = False
    for index in range(info.AceCount):
        ace = ctypes.c_void_p()
        if not advapi.GetAce(dacl, index, ctypes.byref(ace)):
            raise _win_error("get_ace")
        header = ctypes.cast(ace, ctypes.POINTER(_ACE_HEADER)).contents
        if header.AceType in {
            _ACCESS_ALLOWED_COMPOUND_ACE_TYPE,
            _ACCESS_ALLOWED_OBJECT_ACE_TYPE,
            _ACCESS_ALLOWED_CALLBACK_ACE_TYPE,
            _ACCESS_ALLOWED_CALLBACK_OBJECT_ACE_TYPE,
        } and not header.AceFlags & _INHERIT_ONLY_ACE:
            raise AssertionError("privacy_oracle_unsupported_effective_allow_ace")
        if header.AceType != _ACCESS_ALLOWED_ACE_TYPE or header.AceFlags & _INHERIT_ONLY_ACE:
            continue
        mask = ctypes.c_uint32.from_address(ace.value + ctypes.sizeof(_ACE_HEADER)).value
        if not _ace_grants_content(mask):
            continue
        sid = ctypes.c_void_p(ace.value + ctypes.sizeof(_ACE_HEADER) + ctypes.sizeof(wintypes.DWORD))
        allowed += 1
        if any(_same_sid(advapi, sid, broad_sid) for broad_sid in broad_sids):
            broad += 1
            if header.AceFlags & _INHERITED_ACE:
                inherited_broad += 1
        elif not any(_same_sid(advapi, sid, allowed_sid) for allowed_sid in allowed_sids):
            untrusted = True
    return _DescriptorFacts(allowed, broad, inherited_broad, untrusted, owner_class)


def _admin_group_sid(advapi, groups_buffer, administrators_sid):
    header = ctypes.cast(groups_buffer, ctypes.POINTER(_TOKEN_GROUPS_LAYOUT)).contents
    groups = ctypes.cast(
        ctypes.addressof(groups_buffer) + _TOKEN_GROUPS_LAYOUT.Groups.offset,
        ctypes.POINTER(_SID_AND_ATTRIBUTES),
    )
    for index in range(header.GroupCount):
        if _same_sid(advapi, groups[index].Sid, administrators_sid):
            return groups[index].Sid
    return None


def _token_admin_is_disabled(advapi, token, administrators_sid) -> bool:
    groups_buffer = _token_information(advapi, token, _TOKEN_GROUPS)
    header = ctypes.cast(groups_buffer, ctypes.POINTER(_TOKEN_GROUPS_LAYOUT)).contents
    groups = ctypes.cast(
        ctypes.addressof(groups_buffer) + _TOKEN_GROUPS_LAYOUT.Groups.offset,
        ctypes.POINTER(_SID_AND_ATTRIBUTES),
    )
    for index in range(header.GroupCount):
        group = groups[index]
        if _same_sid(advapi, group.Sid, administrators_sid):
            return bool(group.Attributes & _SE_GROUP_USE_FOR_DENY_ONLY) or not bool(group.Attributes & _SE_GROUP_ENABLED)
    return True


def _token_privileges_are_limited(advapi, token) -> bool:
    privileges_buffer = _token_information(advapi, token, _TOKEN_PRIVILEGES)
    header = ctypes.cast(privileges_buffer, ctypes.POINTER(_TOKEN_PRIVILEGES_LAYOUT)).contents
    privileges = ctypes.cast(
        ctypes.addressof(privileges_buffer) + _TOKEN_PRIVILEGES_LAYOUT.Privileges.offset,
        ctypes.POINTER(_LUID_AND_ATTRIBUTES),
    )
    enabled = [privileges[index] for index in range(header.PrivilegeCount) if privileges[index].Attributes & _SE_PRIVILEGE_ENABLED]
    if not enabled:
        return True
    if len(enabled) != 1:
        return False
    change_notify = _LUID()
    if not advapi.LookupPrivilegeValueW(None, "SeChangeNotifyPrivilege", ctypes.byref(change_notify)):
        raise _win_error("lookup_change_notify_privilege")
    return enabled[0].LowPart == change_notify.LowPart and enabled[0].HighPart == change_notify.HighPart


def _restricted_impersonation_token(kernel, advapi, current_token, disabled_sids, restricting_sid=None):
    disabled = (_SID_AND_ATTRIBUTES * len(disabled_sids))(*(_SID_AND_ATTRIBUTES(sid, 0) for sid in disabled_sids))
    restricting = None
    restrict_count = 0
    if restricting_sid is not None:
        restricting = (_SID_AND_ATTRIBUTES * 1)(_SID_AND_ATTRIBUTES(restricting_sid, 0))
        restrict_count = 1
    restricted = wintypes.HANDLE()
    if not advapi.CreateRestrictedToken(
        current_token,
        _DISABLE_MAX_PRIVILEGE,
        len(disabled_sids),
        disabled if disabled_sids else None,
        0,
        None,
        restrict_count,
        restricting,
        ctypes.byref(restricted),
    ):
        raise _win_error("create_restricted_token")
    impersonation = wintypes.HANDLE()
    try:
        if not advapi.DuplicateTokenEx(
            restricted,
            _TOKEN_QUERY | _TOKEN_IMPERSONATE,
            None,
            _SECURITY_IMPERSONATION,
            _TOKEN_IMPERSONATION,
            ctypes.byref(impersonation),
        ):
            raise _win_error("duplicate_impersonation_token")
        return impersonation
    finally:
        _close(kernel, restricted)


def _access_check(advapi, descriptor, token, desired: int) -> bool:
    mapping = _GENERIC_MAPPING(_FILE_GENERIC_READ, _FILE_GENERIC_WRITE, _FILE_GENERIC_EXECUTE, _FILE_ALL_ACCESS)
    requested = wintypes.DWORD(desired)
    advapi.MapGenericMask(ctypes.byref(requested), ctypes.byref(mapping))
    probe = ctypes.create_string_buffer(1)
    needed = wintypes.DWORD(ctypes.sizeof(probe))
    granted = wintypes.DWORD()
    status = wintypes.BOOL()
    advapi.AccessCheck(
        descriptor,
        token,
        requested,
        ctypes.byref(mapping),
        probe,
        ctypes.byref(needed),
        ctypes.byref(granted),
        ctypes.byref(status),
    )
    if not needed.value:
        raise _win_error("access_check_privilege_set")
    privileges = ctypes.create_string_buffer(needed.value)
    if not advapi.AccessCheck(
        descriptor,
        token,
        requested,
        ctypes.byref(mapping),
        privileges,
        ctypes.byref(needed),
        ctypes.byref(granted),
        ctypes.byref(status),
    ):
        raise _win_error("access_check")
    return bool(status.value)


def _restricted_file_io(advapi, token, directory: Path, html_path: Path, expected_html: bytes) -> tuple[bool, bool, bool]:
    probe = directory / f".privacy-probe-{secrets.token_hex(8)}"
    descriptor = -1
    impersonated = False
    try:
        if not advapi.ImpersonateLoggedOnUser(token):
            raise _win_error("impersonate")
        impersonated = True
        try:
            descriptor = os.open(html_path, os.O_RDONLY | os.O_BINARY)
            observed_html = os.read(descriptor, len(expected_html) + 1)
            os.close(descriptor)
            descriptor = -1
            if observed_html != expected_html:
                raise AssertionError("privacy_oracle_restricted_html_read_mismatch")
            descriptor = os.open(probe, os.O_CREAT | os.O_EXCL | os.O_RDWR | os.O_BINARY)
            if os.write(descriptor, b"p") != 1:
                raise AssertionError("privacy_oracle_restricted_probe_write_mismatch")
            os.close(descriptor)
            descriptor = -1
            descriptor = os.open(probe, os.O_RDONLY | os.O_BINARY)
            if os.read(descriptor, 1) != b"p":
                raise AssertionError("privacy_oracle_restricted_probe_read_mismatch")
            os.close(descriptor)
            descriptor = -1
            os.unlink(probe)
            return True, True, True
        except OSError:
            raise AssertionError("privacy_oracle_restricted_file_io_failed") from None
        finally:
            try:
                if descriptor != -1:
                    os.close(descriptor)
                if probe.exists():
                    os.unlink(probe)
            except OSError:
                raise AssertionError("privacy_oracle_restricted_file_cleanup_failed") from None
    finally:
        if impersonated and not advapi.RevertToSelf():
            raise _win_error("revert")


def _broad_content_granted(kernel, advapi, current_token, current_sid, admin_sid, broad_sid, descriptor, desired: int) -> bool:
    disabled = [current_sid]
    if admin_sid is not None:
        disabled.append(admin_sid)
    token = _restricted_impersonation_token(kernel, advapi, current_token, disabled, broad_sid)
    try:
        return _access_check(advapi, descriptor, token, desired)
    finally:
        _close(kernel, token)


def inspect_dashboard_privacy(directory: Path, html_path: Path) -> DashboardPrivacyReceipt:
    """Assert native ownership, DACL effective privacy, and restricted-user usability."""
    kernel, advapi = _api()
    current = _current_token(kernel, advapi)
    descriptors = []
    restricted = None
    try:
        current_user = _token_information(advapi, current, _TOKEN_USER)
        current_sid = ctypes.cast(current_user, ctypes.POINTER(_TOKEN_USER_STRUCT)).contents.User.Sid
        groups = _token_information(advapi, current, _TOKEN_GROUPS)
        sid_buffers = [
            _well_known_sid(advapi, _WIN_LOCAL_SYSTEM_SID),
            _well_known_sid(advapi, _WIN_BUILTIN_ADMINISTRATORS_SID),
            _well_known_sid(advapi, _WIN_WORLD_SID),
            _well_known_sid(advapi, _WIN_AUTHENTICATED_USER_SID),
            _well_known_sid(advapi, _WIN_BUILTIN_USERS_SID),
        ]
        system_sid, administrators_sid, *broad_sids = [ctypes.cast(buffer, ctypes.c_void_p) for buffer in sid_buffers]
        allowed_sids = [current_sid, system_sid, administrators_sid]
        admin_group_sid = _admin_group_sid(advapi, groups, administrators_sid)
        entries = []
        for path in (Path(directory), Path(html_path)):
            owner, _group, dacl, descriptor = _security_descriptor(advapi, path)
            descriptors.append(descriptor)
            entries.append(
                (
                    descriptor,
                    _inspect_descriptor(
                        advapi, owner, dacl, current_sid, allowed_sids, broad_sids, system_sid, administrators_sid
                    ),
                )
            )

        def broad_content_granted(descriptor, rights) -> bool:
            return any(
                _broad_content_granted(
                    kernel, advapi, current, current_sid, admin_group_sid, broad_sid, descriptor, desired
                )
                for broad_sid in broad_sids
                for desired in rights
            )

        directory_broad = broad_content_granted(
            entries[0][0], (_FILE_LIST_DIRECTORY, _FILE_ADD_FILE, _FILE_DELETE_CHILD, _DELETE)
        )
        html_broad = broad_content_granted(
            entries[1][0], (_FILE_READ_DATA, _FILE_WRITE_DATA, _FILE_APPEND_DATA, _DELETE)
        )
        if directory_broad or html_broad:
            raise AssertionError("native_privacy_broad_content")
        if entries[0][1].broad_allow_count or entries[1][1].broad_allow_count:
            raise AssertionError("privacy_oracle_broad_allow_ace")
        if entries[0][1].has_untrusted_allow or entries[1][1].has_untrusted_allow:
            raise AssertionError("privacy_oracle_untrusted_allow_ace")

        disabled_admin = [admin_group_sid] if admin_group_sid is not None else []
        restricted = _restricted_impersonation_token(kernel, advapi, current, disabled_admin)
        if not _token_admin_is_disabled(advapi, restricted, administrators_sid):
            raise AssertionError("privacy_oracle_restricted_admin_enabled")
        if not _token_privileges_are_limited(advapi, restricted):
            raise AssertionError("privacy_oracle_restricted_privileges_not_limited")
        read = _access_check(advapi, entries[1][0], restricted, _GENERIC_READ)
        write = _access_check(advapi, entries[0][0], restricted, _GENERIC_WRITE)
        delete = _access_check(advapi, entries[0][0], restricted, _DELETE)
        try:
            expected_html = Path(html_path).read_bytes()
        except OSError:
            raise AssertionError("privacy_oracle_expected_html_read_failed") from None
        io_read, io_write, io_delete = _restricted_file_io(
            advapi, restricted, Path(directory), Path(html_path), expected_html
        )
        if not all((read, write, delete, io_read, io_write, io_delete)):
            raise AssertionError("privacy_oracle_restricted_current_user_not_usable")
        directory_facts, html_facts = entries[0][1], entries[1][1]
        return DashboardPrivacyReceipt(
            ordinary_access_context="restricted_current_user",
            directory_owner_class=directory_facts.owner_class,
            html_owner_class=html_facts.owner_class,
            directory_owner_matches_current=directory_facts.owner_class == "current_user",
            html_owner_matches_current=html_facts.owner_class == "current_user",
            directory_dacl_present=True,
            html_dacl_present=True,
            directory_allowed_ace_count=directory_facts.allowed_ace_count,
            html_allowed_ace_count=html_facts.allowed_ace_count,
            directory_broad_allow_count=directory_facts.broad_allow_count,
            html_broad_allow_count=html_facts.broad_allow_count,
            directory_inherited_broad_allow_count=directory_facts.inherited_broad_allow_count,
            html_inherited_broad_allow_count=html_facts.inherited_broad_allow_count,
            directory_broad_content_denied=True,
            html_broad_content_denied=True,
            restricted_access_check_read=read,
            restricted_access_check_write=write,
            restricted_access_check_delete=delete,
            restricted_token_read=io_read,
            restricted_token_write=io_write,
            restricted_token_delete=io_delete,
        )
    finally:
        if restricted:
            _close(kernel, restricted)
        for descriptor in descriptors:
            if descriptor:
                kernel.LocalFree(descriptor)
        _close(kernel, current)


@contextmanager
def permissive_directory(path: Path):
    """Temporarily give Everyone inheritable full access to an owned empty directory.

    The caller creates its control child while this context is active.  The child
    therefore receives a genuine inherited broad grant for the negative oracle.
    """
    kernel, advapi = _api()
    path = Path(path)
    if not path.is_dir() or any(path.iterdir()):
        raise AssertionError("privacy_oracle_fixture_directory_not_empty")
    owner, _group, _dacl, original_descriptor = _security_descriptor(advapi, path)
    original_security_information = None
    try:
        _assert_fixture_owned_by_current_token(kernel, advapi, owner)
        original_security_information = _original_dacl_security_information(advapi, original_descriptor)
        everyone = _well_known_sid(advapi, _WIN_WORLD_SID)
        sid_size = advapi.GetLengthSid(everyone)
        if not sid_size:
            raise _win_error("fixture_everyone_sid")
        acl_size = ctypes.sizeof(wintypes.DWORD) * 2 + ctypes.sizeof(_ACE_HEADER) + ctypes.sizeof(wintypes.DWORD) + sid_size
        acl = ctypes.create_string_buffer(acl_size)
        if not advapi.InitializeAcl(acl, ctypes.sizeof(acl), _ACL_REVISION):
            raise _win_error("initialize_fixture_acl")
        if not advapi.AddAccessAllowedAceEx(
            acl,
            _ACL_REVISION,
            _OBJECT_INHERIT_ACE | _CONTAINER_INHERIT_ACE,
            _GENERIC_ALL,
            everyone,
        ):
            raise _win_error("add_fixture_everyone_ace")
        result = advapi.SetNamedSecurityInfoW(
            str(path), _SE_FILE_OBJECT, _DACL_SECURITY_INFORMATION, None, None, acl, None
        )
        if result:
            raise _win_error("set_fixture_dacl")
        yield path
    finally:
        try:
            if original_security_information is not None and not advapi.SetFileSecurityW(
                str(path), original_security_information, original_descriptor
            ):
                raise _win_error("restore_fixture_descriptor")
        finally:
            kernel.LocalFree(original_descriptor)


@contextmanager
def null_dacl_directory(path: Path):
    """Temporarily install a null DACL on an owned empty fixture directory."""
    kernel, advapi = _api()
    path = Path(path)
    if not path.is_dir() or any(path.iterdir()):
        raise AssertionError("privacy_oracle_fixture_directory_not_empty")
    owner, _group, _dacl, original_descriptor = _security_descriptor(advapi, path)
    original_security_information = None
    try:
        _assert_fixture_owned_by_current_token(kernel, advapi, owner)
        original_security_information = _original_dacl_security_information(advapi, original_descriptor)
        result = advapi.SetNamedSecurityInfoW(
            str(path), _SE_FILE_OBJECT, _DACL_SECURITY_INFORMATION, None, None, None, None
        )
        if result:
            raise _win_error("set_fixture_null_dacl")
        yield path
    finally:
        try:
            if original_security_information is not None and not advapi.SetFileSecurityW(
                str(path), original_security_information, original_descriptor
            ):
                raise _win_error("restore_fixture_descriptor")
        finally:
            kernel.LocalFree(original_descriptor)
