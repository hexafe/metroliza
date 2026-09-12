[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$ConfigPath)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$config = Get-Content -Raw -LiteralPath $ConfigPath | ConvertFrom-Json
$ready = [Threading.EventWaitHandle]::OpenExisting($config.ready)
$hold = [Threading.EventWaitHandle]::OpenExisting($config.hold)
$record = @{schema_version=1; stage='shell_initialized'} | ConvertTo-Json -Compress
[IO.File]::AppendAllText($config.phase, $record + [Environment]::NewLine,
    [Text.UTF8Encoding]::new($false))

try {
    if ($config.scenario -eq 'live_shell') {
        $record = @{schema_version=1; stage='shell_ready'} | ConvertTo-Json -Compress
        [IO.File]::AppendAllText($config.state, $record + [Environment]::NewLine,
            [Text.UTF8Encoding]::new($false))
        if (-not $ready.Set()) { throw 'fixture_ready_failed' }
        $hold.WaitOne() | Out-Null
        exit 0
    }

    $release = [Threading.EventWaitHandle]::OpenExisting($config.release)
    try {
        $config.parent_pid = $PID
        [IO.File]::WriteAllText($ConfigPath, ($config | ConvertTo-Json -Compress),
            [Text.UTF8Encoding]::new($false))
        Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using System.Text;

public static class PipeFixture1043 {
    [StructLayout(LayoutKind.Sequential)] struct Security {
        public int length;
        public IntPtr descriptor;
        [MarshalAs(UnmanagedType.Bool)] public bool inherit;
    }
    [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Unicode)] struct Startup {
        public int size;
        public IntPtr reserved, desktop, title;
        public int x, y, width, height, xChars, yChars, fill, flags;
        public ushort show, reservedBytes;
        public IntPtr reservedData, input, output, error;
    }
    [StructLayout(LayoutKind.Sequential)] struct StartupEx {
        public Startup startup;
        public IntPtr attributes;
    }
    [StructLayout(LayoutKind.Sequential)] struct ProcessInfo {
        public IntPtr process, thread;
        public int pid, tid;
    }
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true,
        ExactSpelling=true)]
    static extern bool CreateProcessW(string app, StringBuilder command, IntPtr processAttributes,
        IntPtr threadAttributes, bool inherit, int flags, IntPtr environment, string directory,
        ref StartupEx startup, out ProcessInfo info);
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true,
        ExactSpelling=true)]
    static extern IntPtr CreateFileW(string name, uint access, uint share, ref Security security,
        uint creation, uint flags, IntPtr template);
    [DllImport("kernel32.dll", SetLastError=true)]
    static extern bool SetHandleInformation(IntPtr handle, uint mask, uint flags);
    [DllImport("kernel32.dll", SetLastError=true)]
    static extern bool InitializeProcThreadAttributeList(IntPtr attributes, int count, int flags,
        ref IntPtr size);
    [DllImport("kernel32.dll", SetLastError=true)]
    static extern bool UpdateProcThreadAttribute(IntPtr attributes, uint flags, IntPtr attribute,
        IntPtr value, UIntPtr size, IntPtr previous, IntPtr returnSize);
    [DllImport("kernel32.dll")]
    static extern void DeleteProcThreadAttributeList(IntPtr attributes);
    [DllImport("kernel32.dll")] static extern IntPtr GetStdHandle(int number);
    [DllImport("kernel32.dll")] static extern bool CloseHandle(IntPtr handle);

    static bool Invalid(IntPtr handle) {
        return handle == IntPtr.Zero || handle == new IntPtr(-1);
    }
    static string Quote(string value) {
        if (value.IndexOf('"') >= 0)
            throw new InvalidOperationException("fixture_argument_failed");
        return "\"" + value + "\"";
    }
    static IntPtr File(string name, uint access, uint creation, ref Security security) {
        var handle = CreateFileW(name, access, 7, ref security, creation, 0x80, IntPtr.Zero);
        if (Invalid(handle)) throw new InvalidOperationException("fixture_handle_failed");
        return handle;
    }
    public static void Start(string executable, string[] arguments, string directory,
        bool inheritOutput, string stdoutPath, string stderrPath) {
        var security = new Security();
        security.length = Marshal.SizeOf(security);
        security.inherit = true;
        IntPtr input = IntPtr.Zero, output = IntPtr.Zero, error = IntPtr.Zero;
        IntPtr attributeList = IntPtr.Zero, handleList = IntPtr.Zero;
        bool attributesInitialized = false;
        bool ownOutput = !inheritOutput;
        var info = new ProcessInfo();
        try {
            input = File("NUL", 0x80000000, 3, ref security);
            output = inheritOutput ? GetStdHandle(-11)
                : File(stdoutPath, 0x40000000, 2, ref security);
            error = inheritOutput ? GetStdHandle(-12)
                : File(stderrPath, 0x40000000, 2, ref security);
            if (Invalid(input) || Invalid(output) || Invalid(error)
                || !SetHandleInformation(input, 1, 1)
                || !SetHandleInformation(output, 1, 1)
                || !SetHandleInformation(error, 1, 1))
                throw new InvalidOperationException("fixture_handle_failed");
            IntPtr attributeBytes = IntPtr.Zero;
            if (InitializeProcThreadAttributeList(IntPtr.Zero, 1, 0, ref attributeBytes)
                || attributeBytes == IntPtr.Zero || Marshal.GetLastWin32Error() != 122)
                throw new InvalidOperationException("fixture_attribute_failed");
            attributeList = Marshal.AllocHGlobal(attributeBytes);
            if (!InitializeProcThreadAttributeList(attributeList, 1, 0, ref attributeBytes))
                throw new InvalidOperationException("fixture_attribute_failed");
            attributesInitialized = true;
            handleList = Marshal.AllocHGlobal(IntPtr.Size * 3);
            Marshal.WriteIntPtr(handleList, 0, input);
            Marshal.WriteIntPtr(handleList, IntPtr.Size, output);
            Marshal.WriteIntPtr(handleList, IntPtr.Size * 2, error);
            if (!UpdateProcThreadAttribute(attributeList, 0, new IntPtr(0x00020002),
                handleList, new UIntPtr((uint)(IntPtr.Size * 3)), IntPtr.Zero, IntPtr.Zero))
                throw new InvalidOperationException("fixture_attribute_failed");
            var startup = new StartupEx();
            startup.startup.size = Marshal.SizeOf(startup);
            startup.startup.flags = 0x100;
            startup.startup.input = input;
            startup.startup.output = output;
            startup.startup.error = error;
            startup.attributes = attributeList;
            var command = new StringBuilder(Quote(executable));
            foreach (var argument in arguments) command.Append(" ").Append(Quote(argument));
            if (!CreateProcessW(executable, command, IntPtr.Zero, IntPtr.Zero, true, 0x08080000,
                IntPtr.Zero, directory, ref startup, out info))
                throw new InvalidOperationException("fixture_start_failed");
        }
        finally {
            if (!Invalid(info.thread)) CloseHandle(info.thread);
            if (!Invalid(info.process)) CloseHandle(info.process);
            if (attributesInitialized) DeleteProcThreadAttributeList(attributeList);
            if (attributeList != IntPtr.Zero) Marshal.FreeHGlobal(attributeList);
            if (handleList != IntPtr.Zero) Marshal.FreeHGlobal(handleList);
            if (!Invalid(input)) CloseHandle(input);
            if (ownOutput && !Invalid(output)) CloseHandle(output);
            if (ownOutput && !Invalid(error)) CloseHandle(error);
        }
    }
}
'@
        $record = @{schema_version=1; stage='native_factory_ready'} | ConvertTo-Json -Compress
        [IO.File]::AppendAllText($config.phase, $record + [Environment]::NewLine,
            [Text.UTF8Encoding]::new($false))
        [PipeFixture1043]::Start(
            $config.python,
            [string[]]@('-I', '-S', $config.child, 'child', $ConfigPath),
            $config.root,
            ($config.scenario -eq 'retained_pipes'),
            $config.stdout,
            $config.stderr
        )
        $record = @{schema_version=1; stage='child_created'} | ConvertTo-Json -Compress
        [IO.File]::AppendAllText($config.phase, $record + [Environment]::NewLine,
            [Text.UTF8Encoding]::new($false))
        if (-not $ready.WaitOne(10000)) { throw 'fixture_ready_failed' }
        if (-not $release.Set()) { throw 'fixture_release_failed' }
    }
    finally {
        $release.Dispose()
    }
}
finally {
    $ready.Dispose()
    $hold.Dispose()
}
