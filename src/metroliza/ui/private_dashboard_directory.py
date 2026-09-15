"""Private, session-owned directories for realtime dashboard HTML output."""

from __future__ import annotations

import ctypes
import os
from pathlib import Path
import secrets
import shutil
import tempfile
import weakref
from ctypes import wintypes


_PREFIX = "metroliza-realtime-dashboard-"
_ERROR = "private_dashboard_directory_unavailable"
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

# Windows security and file constants.
_DACL_SECURITY_INFORMATION = 0x00000004
_OWNER_SECURITY_INFORMATION = 0x00000001
_SE_FILE_OBJECT = 1
_SE_DACL_PROTECTED = 0x1000
_FILE_ALL_ACCESS = 0x001F01FF
_FILE_SHARE_READ = 0x00000001
_FILE_SHARE_WRITE = 0x00000002
_FILE_READ_ATTRIBUTES = 0x00000080
_READ_CONTROL = 0x00020000
_DELETE = 0x00010000
_FILE_ATTRIBUTE_DIRECTORY = 0x00000010
_FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400
_FILE_DISPOSITION_INFO = 4
_FILE_CREATE = 2
_FILE_CREATED = 2
_FILE_DIRECTORY_FILE = 0x00000001
_FILE_SYNCHRONOUS_IO_NONALERT = 0x00000020
_OBJ_CASE_INSENSITIVE = 0x00000040
_SYNCHRONIZE = 0x00100000
_TOKEN_QUERY = 0x0008
_TOKEN_USER = 1
_WIN_LOCAL_SYSTEM_SID = 22
_WIN_BUILTIN_ADMINISTRATORS_SID = 26
_ACL_REVISION = 2
_ACCESS_ALLOWED_ACE_TYPE = 0
_OBJECT_INHERIT_ACE = 0x01
_CONTAINER_INHERIT_ACE = 0x02
_INHERIT_FLAGS = _OBJECT_INHERIT_ACE | _CONTAINER_INHERIT_ACE
_STATUS_SUCCESS = 0
_STATUS_OBJECT_NAME_COLLISION = ctypes.c_int32(0xC0000035).value


class PrivateDashboardDirectoryError(RuntimeError):
    """Bounded failure safe to display from a Qt callback."""

    def __init__(self, message: str = _ERROR) -> None:
        super().__init__(message if message == _ERROR else _ERROR)


class _SID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", wintypes.DWORD)]


class _TOKEN_USER_STRUCT(ctypes.Structure):
    _fields_ = [("User", _SID_AND_ATTRIBUTES)]


class _SECURITY_DESCRIPTOR(ctypes.Structure):
    _fields_ = [
        ("Revision", ctypes.c_ubyte),
        ("Sbz1", ctypes.c_ubyte),
        ("Control", wintypes.WORD),
        ("Owner", ctypes.c_void_p),
        ("Group", ctypes.c_void_p),
        ("Sacl", ctypes.c_void_p),
        ("Dacl", ctypes.c_void_p),
    ]


class _SECURITY_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("nLength", wintypes.DWORD), ("lpSecurityDescriptor", ctypes.c_void_p), ("bInheritHandle", wintypes.BOOL)]


class _ACL_SIZE_INFORMATION(ctypes.Structure):
    _fields_ = [("AceCount", wintypes.DWORD), ("AclBytesInUse", wintypes.DWORD), ("AclBytesFree", wintypes.DWORD)]


class _ACE_HEADER(ctypes.Structure):
    _fields_ = [("AceType", ctypes.c_ubyte), ("AceFlags", ctypes.c_ubyte), ("AceSize", ctypes.c_ushort)]


class _BY_HANDLE_FILE_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("dwFileAttributes", wintypes.DWORD),
        ("ftCreationTimeLow", wintypes.DWORD),
        ("ftCreationTimeHigh", wintypes.DWORD),
        ("ftLastAccessTimeLow", wintypes.DWORD),
        ("ftLastAccessTimeHigh", wintypes.DWORD),
        ("ftLastWriteTimeLow", wintypes.DWORD),
        ("ftLastWriteTimeHigh", wintypes.DWORD),
        ("dwVolumeSerialNumber", wintypes.DWORD),
        ("nFileSizeHigh", wintypes.DWORD),
        ("nFileSizeLow", wintypes.DWORD),
        ("nNumberOfLinks", wintypes.DWORD),
        ("nFileIndexHigh", wintypes.DWORD),
        ("nFileIndexLow", wintypes.DWORD),
    ]


class _FILE_DISPOSITION_INFO_STRUCT(ctypes.Structure):
    _fields_ = [("DeleteFile", ctypes.c_ubyte)]


class _UNICODE_STRING(ctypes.Structure):
    _fields_ = [
        ("Length", wintypes.USHORT),
        ("MaximumLength", wintypes.USHORT),
        ("Buffer", wintypes.LPWSTR),
    ]


class _OBJECT_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("Length", wintypes.ULONG),
        ("RootDirectory", wintypes.HANDLE),
        ("ObjectName", ctypes.POINTER(_UNICODE_STRING)),
        ("Attributes", wintypes.ULONG),
        ("SecurityDescriptor", ctypes.c_void_p),
        ("SecurityQualityOfService", ctypes.c_void_p),
    ]


class _IO_STATUS_BLOCK_STATUS(ctypes.Union):
    _fields_ = [("Status", ctypes.c_int32), ("Pointer", ctypes.c_void_p)]


class _IO_STATUS_BLOCK(ctypes.Structure):
    _fields_ = [("Status", _IO_STATUS_BLOCK_STATUS), ("Information", ctypes.c_size_t)]


class _WindowsPrivateDashboardDirectory:
    """A pinned, verified Windows directory with tempfile-compatible surface."""

    def __init__(self, name: str, handle, kernel) -> None:
        self.name = name
        self._handle = handle
        self._kernel = kernel
        self._closed = False
        self._finalizer = weakref.finalize(self, _finalize_pinned_directory, name, handle, kernel)

    def cleanup(self) -> None:
        """Delete only this pinned directory; never re-open its name after closing."""
        if self._closed:
            return
        handle = self._handle
        try:
            for child in Path(self.name).iterdir():
                if child.is_dir():
                    shutil.rmtree(child)
                else:
                    child.unlink()
            _mark_empty_directory_for_deletion(self._kernel, handle)
        except (OSError, PrivateDashboardDirectoryError):
            raise PrivateDashboardDirectoryError() from None
        if not self._kernel.CloseHandle(handle):
            raise PrivateDashboardDirectoryError()
        self._handle = None
        self._closed = True
        self._finalizer.detach()


def _windows_api():
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    ntdll = ctypes.WinDLL("ntdll", use_last_error=True)
    kernel.GetCurrentProcess.argtypes = []
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    kernel.GetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.POINTER(_BY_HANDLE_FILE_INFORMATION)]
    kernel.GetFileInformationByHandle.restype = wintypes.BOOL
    kernel.SetFileInformationByHandle.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
    kernel.SetFileInformationByHandle.restype = wintypes.BOOL
    advapi.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    advapi.OpenProcessToken.restype = wintypes.BOOL
    advapi.GetTokenInformation.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    advapi.GetTokenInformation.restype = wintypes.BOOL
    advapi.CreateWellKnownSid.argtypes = [wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD)]
    advapi.CreateWellKnownSid.restype = wintypes.BOOL
    advapi.EqualSid.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    advapi.EqualSid.restype = wintypes.BOOL
    advapi.GetLengthSid.argtypes = [ctypes.c_void_p]
    advapi.GetLengthSid.restype = wintypes.DWORD
    advapi.InitializeAcl.argtypes = [ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD]
    advapi.InitializeAcl.restype = wintypes.BOOL
    advapi.AddAccessAllowedAceEx.argtypes = [ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
    advapi.AddAccessAllowedAceEx.restype = wintypes.BOOL
    advapi.InitializeSecurityDescriptor.argtypes = [ctypes.c_void_p, wintypes.DWORD]
    advapi.InitializeSecurityDescriptor.restype = wintypes.BOOL
    advapi.SetSecurityDescriptorDacl.argtypes = [ctypes.c_void_p, wintypes.BOOL, ctypes.c_void_p, wintypes.BOOL]
    advapi.SetSecurityDescriptorDacl.restype = wintypes.BOOL
    advapi.SetSecurityDescriptorControl.argtypes = [ctypes.c_void_p, wintypes.WORD, wintypes.WORD]
    advapi.SetSecurityDescriptorControl.restype = wintypes.BOOL
    advapi.GetSecurityInfo.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p),
    ]
    advapi.GetSecurityInfo.restype = wintypes.DWORD
    advapi.GetAclInformation.argtypes = [ctypes.c_void_p, ctypes.POINTER(_ACL_SIZE_INFORMATION), wintypes.DWORD, wintypes.DWORD]
    advapi.GetAclInformation.restype = wintypes.BOOL
    advapi.GetAce.argtypes = [ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p)]
    advapi.GetAce.restype = wintypes.BOOL
    advapi.GetSecurityDescriptorControl.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.WORD), ctypes.POINTER(wintypes.DWORD)]
    advapi.GetSecurityDescriptorControl.restype = wintypes.BOOL
    ntdll.RtlDosPathNameToNtPathName_U_WithStatus.argtypes = [
        wintypes.LPCWSTR, ctypes.POINTER(_UNICODE_STRING), ctypes.POINTER(wintypes.LPWSTR), ctypes.c_void_p,
    ]
    ntdll.RtlDosPathNameToNtPathName_U_WithStatus.restype = ctypes.c_int32
    ntdll.RtlFreeUnicodeString.argtypes = [ctypes.POINTER(_UNICODE_STRING)]
    ntdll.RtlFreeUnicodeString.restype = None
    ntdll.NtCreateFile.argtypes = [
        ctypes.POINTER(wintypes.HANDLE), wintypes.DWORD, ctypes.POINTER(_OBJECT_ATTRIBUTES),
        ctypes.POINTER(_IO_STATUS_BLOCK), ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
        wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
    ]
    ntdll.NtCreateFile.restype = ctypes.c_int32
    return kernel, advapi, ntdll


def _current_user_sid(kernel, advapi):
    token = wintypes.HANDLE()
    if not advapi.OpenProcessToken(kernel.GetCurrentProcess(), _TOKEN_QUERY, ctypes.byref(token)):
        raise PrivateDashboardDirectoryError()
    try:
        needed = wintypes.DWORD()
        advapi.GetTokenInformation(token, _TOKEN_USER, None, 0, ctypes.byref(needed))
        if not needed.value:
            raise PrivateDashboardDirectoryError()
        buffer = ctypes.create_string_buffer(needed.value)
        if not advapi.GetTokenInformation(token, _TOKEN_USER, buffer, needed, ctypes.byref(needed)):
            raise PrivateDashboardDirectoryError()
        return buffer, ctypes.cast(buffer, ctypes.POINTER(_TOKEN_USER_STRUCT)).contents.User.Sid
    finally:
        kernel.CloseHandle(token)


def _well_known_sid(advapi, sid_type: int):
    needed = wintypes.DWORD()
    advapi.CreateWellKnownSid(sid_type, None, None, ctypes.byref(needed))
    if not needed.value:
        raise PrivateDashboardDirectoryError()
    buffer = ctypes.create_string_buffer(needed.value)
    if not advapi.CreateWellKnownSid(sid_type, None, buffer, ctypes.byref(needed)):
        raise PrivateDashboardDirectoryError()
    return buffer, ctypes.cast(buffer, ctypes.c_void_p)


def _security_attributes(advapi, user_sid):
    system_buffer, system_sid = _well_known_sid(advapi, _WIN_LOCAL_SYSTEM_SID)
    admin_buffer, admin_sid = _well_known_sid(advapi, _WIN_BUILTIN_ADMINISTRATORS_SID)
    sid_buffers = (system_buffer, admin_buffer)
    sid_sizes = [advapi.GetLengthSid(sid) for sid in (user_sid, system_sid, admin_sid)]
    if not all(sid_sizes):
        raise PrivateDashboardDirectoryError()
    acl_size = ctypes.sizeof(wintypes.DWORD) * 2 + sum(
        ctypes.sizeof(_ACE_HEADER) + ctypes.sizeof(wintypes.DWORD) + size for size in sid_sizes
    )
    acl = ctypes.create_string_buffer(acl_size)
    if not advapi.InitializeAcl(acl, ctypes.sizeof(acl), _ACL_REVISION):
        raise PrivateDashboardDirectoryError()
    for sid in (user_sid, system_sid, admin_sid):
        if not advapi.AddAccessAllowedAceEx(acl, _ACL_REVISION, _INHERIT_FLAGS, _FILE_ALL_ACCESS, sid):
            raise PrivateDashboardDirectoryError()
    descriptor = _SECURITY_DESCRIPTOR()
    if not advapi.InitializeSecurityDescriptor(ctypes.byref(descriptor), 1):
        raise PrivateDashboardDirectoryError()
    if not advapi.SetSecurityDescriptorDacl(ctypes.byref(descriptor), True, acl, False):
        raise PrivateDashboardDirectoryError()
    if not advapi.SetSecurityDescriptorControl(ctypes.byref(descriptor), _SE_DACL_PROTECTED, _SE_DACL_PROTECTED):
        raise PrivateDashboardDirectoryError()
    attributes = _SECURITY_ATTRIBUTES(ctypes.sizeof(_SECURITY_ATTRIBUTES), ctypes.cast(ctypes.byref(descriptor), ctypes.c_void_p), False)
    return attributes, (acl, descriptor, sid_buffers)


def _validate_pinned_identity(kernel, advapi, handle, allowed_sids) -> None:
    information = _BY_HANDLE_FILE_INFORMATION()
    if not kernel.GetFileInformationByHandle(handle, ctypes.byref(information)):
        raise PrivateDashboardDirectoryError()
    if not information.dwFileAttributes & _FILE_ATTRIBUTE_DIRECTORY or information.dwFileAttributes & _FILE_ATTRIBUTE_REPARSE_POINT:
        raise PrivateDashboardDirectoryError()
    owner = ctypes.c_void_p()
    dacl = ctypes.c_void_p()
    descriptor = ctypes.c_void_p()
    result = advapi.GetSecurityInfo(
        handle, _SE_FILE_OBJECT, _OWNER_SECURITY_INFORMATION | _DACL_SECURITY_INFORMATION,
        ctypes.byref(owner), None, ctypes.byref(dacl), None, ctypes.byref(descriptor),
    )
    if result:
        raise PrivateDashboardDirectoryError()
    try:
        if not owner or not any(advapi.EqualSid(owner, allowed) for allowed in allowed_sids):
            raise PrivateDashboardDirectoryError()
    finally:
        if descriptor:
            kernel.LocalFree(descriptor)


def _validate_pinned_directory(kernel, advapi, handle, allowed_sids) -> None:
    _validate_pinned_identity(kernel, advapi, handle, allowed_sids)
    owner = ctypes.c_void_p()
    dacl = ctypes.c_void_p()
    descriptor = ctypes.c_void_p()
    result = advapi.GetSecurityInfo(
        handle, _SE_FILE_OBJECT, _OWNER_SECURITY_INFORMATION | _DACL_SECURITY_INFORMATION,
        ctypes.byref(owner), None, ctypes.byref(dacl), None, ctypes.byref(descriptor),
    )
    if result:
        raise PrivateDashboardDirectoryError()
    try:
        _validate_protected_allowlist(advapi, dacl, descriptor, allowed_sids)
    finally:
        if descriptor:
            kernel.LocalFree(descriptor)


def _validate_protected_allowlist(advapi, dacl, descriptor, allowed_sids) -> None:
    control = wintypes.WORD()
    revision = wintypes.DWORD()
    if not dacl or not advapi.GetSecurityDescriptorControl(descriptor, ctypes.byref(control), ctypes.byref(revision)):
        raise PrivateDashboardDirectoryError()
    if not control.value & _SE_DACL_PROTECTED:
        raise PrivateDashboardDirectoryError()
    info = _ACL_SIZE_INFORMATION()
    if not advapi.GetAclInformation(dacl, ctypes.byref(info), ctypes.sizeof(info), 2) or info.AceCount != 3:
        raise PrivateDashboardDirectoryError()
    seen = {_validated_ace_position(advapi, dacl, index, allowed_sids) for index in range(info.AceCount)}
    if seen != {0, 1, 2}:
        raise PrivateDashboardDirectoryError()


def _validated_ace_position(advapi, dacl, index: int, allowed_sids) -> int:
    ace = ctypes.c_void_p()
    if not advapi.GetAce(dacl, index, ctypes.byref(ace)):
        raise PrivateDashboardDirectoryError()
    header = ctypes.cast(ace, ctypes.POINTER(_ACE_HEADER)).contents
    if header.AceType != _ACCESS_ALLOWED_ACE_TYPE or header.AceFlags != _INHERIT_FLAGS:
        raise PrivateDashboardDirectoryError()
    mask = ctypes.c_uint32.from_address(ace.value + ctypes.sizeof(_ACE_HEADER)).value
    sid = ctypes.c_void_p(ace.value + ctypes.sizeof(_ACE_HEADER) + ctypes.sizeof(wintypes.DWORD))
    for position, allowed in enumerate(allowed_sids):
        if advapi.EqualSid(sid, allowed) and mask == _FILE_ALL_ACCESS:
            return position
    raise PrivateDashboardDirectoryError()


def _mark_empty_directory_for_deletion(kernel, handle) -> None:
    disposition = _FILE_DISPOSITION_INFO_STRUCT(True)
    if not kernel.SetFileInformationByHandle(
        handle, _FILE_DISPOSITION_INFO, ctypes.byref(disposition), ctypes.sizeof(disposition)
    ):
        raise PrivateDashboardDirectoryError()


def _finalize_pinned_directory(name: str, handle, kernel) -> None:
    """Best-effort tempfile-style finalization through the verified pinned handle."""
    try:
        for child in Path(name).iterdir():
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
        _mark_empty_directory_for_deletion(kernel, handle)
    except (OSError, PrivateDashboardDirectoryError):
        pass
    finally:
        kernel.CloseHandle(handle)


def _nt_success(status: int) -> bool:
    return status >= 0


def _valid_handle(handle) -> bool:
    value = handle.value if hasattr(handle, "value") else handle
    return bool(value) and value != _INVALID_HANDLE_VALUE


def _nt_create_private_directory(ntdll, candidate: Path, attributes) -> tuple[int, int | None, int]:
    """Atomically create a directory and return its pin, without a path reopen."""
    native_path = _UNICODE_STRING()
    status = ntdll.RtlDosPathNameToNtPathName_U_WithStatus(
        str(candidate), ctypes.byref(native_path), None, None,
    )
    if not _nt_success(status):
        return status, None, 0
    try:
        handle = wintypes.HANDLE()
        operation = _OBJECT_ATTRIBUTES(
            ctypes.sizeof(_OBJECT_ATTRIBUTES), None, ctypes.pointer(native_path), _OBJ_CASE_INSENSITIVE,
            attributes.lpSecurityDescriptor, None,
        )
        result = _IO_STATUS_BLOCK()
        status = ntdll.NtCreateFile(
            ctypes.byref(handle), _DELETE | _READ_CONTROL | _FILE_READ_ATTRIBUTES | _SYNCHRONIZE,
            ctypes.byref(operation), ctypes.byref(result), None, 0,
            _FILE_SHARE_READ | _FILE_SHARE_WRITE, _FILE_CREATE,
            _FILE_DIRECTORY_FILE | _FILE_SYNCHRONOUS_IO_NONALERT,
            None, 0,
        )
        return status, handle.value, result.Information
    finally:
        ntdll.RtlFreeUnicodeString(ctypes.byref(native_path))


def _create_unique_private_directory(kernel, ntdll, parent: Path, attributes) -> tuple[Path, int]:
    for _attempt in range(32):
        candidate = parent / f"{_PREFIX}{secrets.token_hex(16)}"
        status, handle, information = _nt_create_private_directory(ntdll, candidate, attributes)
        if status == _STATUS_OBJECT_NAME_COLLISION:
            if _valid_handle(handle):
                kernel.CloseHandle(handle)
            continue
        if status == _STATUS_SUCCESS and information == _FILE_CREATED and _valid_handle(handle):
            return candidate, handle
        if _valid_handle(handle):
            kernel.CloseHandle(handle)
        # A pending/non-final NTSTATUS or any non-FILE_CREATED outcome is never accepted.
        raise PrivateDashboardDirectoryError()
    raise PrivateDashboardDirectoryError()


def _create_windows_private_directory_impl():
    kernel, advapi, ntdll = _windows_api()
    user_buffer, user_sid = _current_user_sid(kernel, advapi)
    attributes, buffers = _security_attributes(advapi, user_sid)
    _acl, _descriptor, sid_buffers = buffers  # Keep native DACL/SID buffers alive through NtCreateFile.
    system_sid = ctypes.cast(sid_buffers[0], ctypes.c_void_p)
    admin_sid = ctypes.cast(sid_buffers[1], ctypes.c_void_p)
    parent = Path(tempfile.gettempdir()).resolve()
    handle = None
    owned_identity_verified = False
    try:
        allowed_sids = (user_sid, system_sid, admin_sid)
        created_path, handle = _create_unique_private_directory(kernel, ntdll, parent, attributes)
        _validate_pinned_identity(kernel, advapi, handle, allowed_sids)
        owned_identity_verified = True
        _validate_pinned_directory(kernel, advapi, handle, allowed_sids)
        return _WindowsPrivateDashboardDirectory(str(created_path), handle, kernel)
    except (PrivateDashboardDirectoryError, OSError) as error:
        if handle:
            if owned_identity_verified:
                try:
                    _mark_empty_directory_for_deletion(kernel, handle)
                except PrivateDashboardDirectoryError:
                    pass
            kernel.CloseHandle(handle)
        # Cleanup is handle-directed; no unverified name is ever path-deleted.
        if isinstance(error, PrivateDashboardDirectoryError):
            raise
        raise PrivateDashboardDirectoryError() from None


def _create_windows_private_directory():
    try:
        return _create_windows_private_directory_impl()
    except PrivateDashboardDirectoryError:
        raise
    except OSError:
        raise PrivateDashboardDirectoryError() from None


def create_private_dashboard_directory():
    """Return a cleanup-compatible private dashboard directory for this session."""
    if os.name != "nt":
        try:
            return tempfile.TemporaryDirectory(prefix=_PREFIX)
        except OSError:
            raise PrivateDashboardDirectoryError() from None
    return _create_windows_private_directory()
