[CmdletBinding()]
param(
    [string]$PdfPath,
    [string]$DbFile,
    [string]$OutputPath,
    [string]$VenvDir = '.venv',
    [switch]$Compact
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function ConvertTo-NativeArgument([string]$Value) {
    $escaped = [regex]::Replace($Value, '(\\*)"', '$1$1\"')
    $escaped = [regex]::Replace($escaped, '(\\+)$', '$1$1')
    return '"' + $escaped + '"'
}

function ConvertTo-SafeDiagnostic([string]$Text) {
    $data = $Text | ConvertFrom-Json
    if ($data.schema_version -ne 1 -or @($data.checks).Count -eq 0 -or @($data.checks).Count -gt 9) {
        throw 'protocol_error'
    }
    $ids = @('runtime_config', 'models', 'runtime_import', 'engine_smoke', 'pdf', 'database', 'alternatives', 'diagnostic', 'publication')
    $reasons = @('ok', 'not_selected', 'not_requested', 'ocr_disabled', 'invalid_configuration',
        'missing_models', 'invalid_models', 'import_failed', 'accelerator_unavailable', 'smoke_failed', 'input_unreadable',
        'invalid_pdf', 'extraction_failed', 'metadata_absent', 'ocr_no_records', 'database_missing',
        'schema_unsupported', 'database_unreadable', 'no_matching_rows', 'timeout', 'child_failed',
        'protocol_error', 'output_limit', 'interrupted', 'not_completed', 'output_failed', 'output_alias', 'invalid_arguments')
    $counts = @('model_count', 'missing_count', 'matching_rows', 'metadata_fields', 'header_items',
        'filename_fields', 'header_fields', 'other_fields', 'page_count')
    $versions = @('python_version', 'engine_version', 'rapidocr_version', 'numpy_version', 'cv2_version')
    $checks = @()
    $seen = @()
    foreach ($check in $data.checks) {
        if ($check.id -isnot [string] -or $check.id -cin $seen -or $check.id -cnotin $ids -or $check.requirement -notin @('required', 'advisory') -or
            $check.status -notin @('pass', 'fail', 'skipped') -or $check.reason -notin $reasons) {
            throw 'protocol_error'
        }
        if ($check.status -ceq 'pass' -and $check.reason -cne 'ok') {
            if ($check.id -cnotin @('pdf', 'database') -or $check.reason -cnotin @('metadata_absent', 'ocr_no_records', 'no_matching_rows', 'ocr_disabled')) { throw 'protocol_error' }
        }
        elseif ($check.status -ceq 'skipped' -and $check.reason -cnotin @('not_selected', 'not_requested', 'ocr_disabled', 'not_completed')) { throw 'protocol_error' }
        elseif ($check.status -ceq 'fail' -and $check.reason -cin @('ok', 'not_selected', 'not_requested', 'metadata_absent', 'ocr_no_records', 'no_matching_rows', 'ocr_disabled')) { throw 'protocol_error' }
        $seen += $check.id
        $facts = @{}
        foreach ($fact in $check.facts.PSObject.Properties) {
            $name = $fact.Name
            $value = $fact.Value
            $valid = ($name -eq 'engine' -and $value -cin @('onnxruntime', 'openvino', 'tensorrt')) -or
                ($name -eq 'accelerator' -and $value -cin @('cpu', 'cuda', 'dml', 'coreml')) -or
                ($name -eq 'extraction_mode' -and $value -cin @('none', 'words', 'ocr')) -or
                ($name -in $counts -and ($value -is [int] -or $value -is [long]) -and $value -ge 0 -and $value -le 1000000) -or
                ($name -in $versions -and $value -is [string] -and $value -cmatch '^[0-9]{1,4}(\.[0-9]{1,4}){1,3}$')
            if (-not $valid) { throw 'protocol_error' }
            $facts[$name] = $value
        }
        $checks += @{id=$check.id; requirement=$check.requirement; status=$check.status; reason=$check.reason; facts=$facts}
    }
    return @{schema_version=1; checks=$checks}
}

# A per-invocation job owns every descendant, even if its parent has exited.
# No installation, service, global process state or user cache is involved.
function Initialize-DiagnosticJobType {
if (-not ('OcrDiagnosticJob1002' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.Diagnostics;
using System.IO;
using System.IO.Pipes;
using System.Runtime.InteropServices;
using System.Text;
public sealed class OcrDiagnosticJob1002 : IDisposable {
    [StructLayout(LayoutKind.Sequential)] struct Basic {
        public long processTime, jobTime;
        public uint flags;
        public UIntPtr minWorking, maxWorking;
        public uint active;
        public UIntPtr affinity;
        public uint priority, scheduling;
    }
    [StructLayout(LayoutKind.Sequential)] struct Extended {
        public Basic basic;
        public ulong readOps, writeOps, otherOps, readBytes, writeBytes, otherBytes;
        public UIntPtr processMemory, jobMemory, peakProcess, peakJob;
    }
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode)] static extern IntPtr CreateJobObject(IntPtr attributes, string name);
    [DllImport("kernel32.dll")] static extern bool SetInformationJobObject(IntPtr job, int type, ref Extended info, uint length);
    [DllImport("kernel32.dll")] static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);
    [DllImport("kernel32.dll")] static extern bool CloseHandle(IntPtr handle);
    [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Unicode)] struct Startup {
        public uint size;
        public string reserved, desktop, title;
        public uint x, y, width, height, xChars, yChars, fill, flags;
        public ushort show, reservedBytes;
        public IntPtr reservedData, input, output, error;
    }
    [StructLayout(LayoutKind.Sequential)] struct ProcessInfo {
        public IntPtr process, thread;
        public uint pid, tid;
    }
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
    static extern bool CreateProcess(string executable, StringBuilder command, IntPtr processSecurity,
        IntPtr threadSecurity, bool inherit, uint flags, IntPtr environment, string directory,
        ref Startup startup, out ProcessInfo info);
    [DllImport("kernel32.dll")] static extern uint ResumeThread(IntPtr thread);
    [DllImport("kernel32.dll")] static extern bool TerminateProcess(IntPtr process, uint code);
    [DllImport("kernel32.dll")] static extern uint WaitForSingleObject(IntPtr process, uint timeout);
    public AnonymousPipeServerStream Input, Output, Error;
    IntPtr handle;
    public OcrDiagnosticJob1002() {
        handle = CreateJobObject(IntPtr.Zero, null);
        var limits = new Extended();
        limits.basic.flags = 0x2000;
        if (handle == IntPtr.Zero || !SetInformationJobObject(handle, 9, ref limits, (uint)Marshal.SizeOf(limits))) {
            Dispose(); throw new InvalidOperationException("job_unavailable");
        }
    }
    public void Assign(IntPtr process) {
        if (!AssignProcessToJobObject(handle, process)) throw new InvalidOperationException("job_unavailable");
    }
    public Process Start(string executable, string arguments, string directory) {
        Input = new AnonymousPipeServerStream(PipeDirection.Out, HandleInheritability.Inheritable);
        Output = new AnonymousPipeServerStream(PipeDirection.In, HandleInheritability.Inheritable);
        Error = new AnonymousPipeServerStream(PipeDirection.In, HandleInheritability.Inheritable);
        var startup = new Startup();
        startup.size = (uint)Marshal.SizeOf(startup);
        startup.flags = 0x100; // STARTF_USESTDHANDLES
        startup.input = Input.ClientSafePipeHandle.DangerousGetHandle();
        startup.output = Output.ClientSafePipeHandle.DangerousGetHandle();
        startup.error = Error.ClientSafePipeHandle.DangerousGetHandle();
        var info = new ProcessInfo();
        Process process = null;
        try {
            var command = new StringBuilder("\"" + executable + "\" " + arguments);
            // No interpreter/startup hook/venv redirector runs before assignment.
            if (!CreateProcess(executable, command, IntPtr.Zero, IntPtr.Zero, true,
                0x08000004, IntPtr.Zero, directory, ref startup, out info))
                throw new InvalidOperationException("start_failed");
            Assign(info.process);
            process = Process.GetProcessById((int)info.pid);
            if (process.Handle == IntPtr.Zero || ResumeThread(info.thread) != 1)
                throw new InvalidOperationException("resume_failed");
            return process;
        }
        catch {
            if (info.process != IntPtr.Zero) {
                TerminateProcess(info.process, 1);
                WaitForSingleObject(info.process, 10000);
            }
            if (process != null) process.Dispose();
            throw;
        }
        finally {
            if (info.thread != IntPtr.Zero) CloseHandle(info.thread);
            if (info.process != IntPtr.Zero) CloseHandle(info.process);
            Input.DisposeLocalCopyOfClientHandle();
            Output.DisposeLocalCopyOfClientHandle();
            Error.DisposeLocalCopyOfClientHandle();
        }
    }
    public void Dispose() {
        if (handle != IntPtr.Zero) { CloseHandle(handle); handle = IntPtr.Zero; }
        if (Input != null) Input.Dispose();
        if (Output != null) Output.Dispose();
        if (Error != null) Error.Dispose();
    }
}
'@
}
}

$process = $null
$started = $false
$job = $null
$diagnosticExit = 1
try {
    $deadline = [DateTime]::UtcNow.AddMinutes(20)
    Initialize-DiagnosticJobType
    $repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
    $venvPath = if ([System.IO.Path]::IsPathRooted($VenvDir)) { $VenvDir } else { Join-Path $repoRoot $VenvDir }
    $python = Join-Path $venvPath 'Scripts/python.exe'
    if (-not (Test-Path -LiteralPath $python)) {
        $command = Get-Command python -ErrorAction SilentlyContinue
        if (-not $command) { $command = Get-Command py -ErrorAction SilentlyContinue }
        if (-not $command) { throw 'python_unavailable' }
        $python = $command.Source
    }
    if ($PSBoundParameters.ContainsKey('OutputPath')) {
        if (-not $OutputPath) { throw 'invalid_arguments' }
        if (-not [System.IO.Path]::IsPathRooted($OutputPath)) { $OutputPath = Join-Path $repoRoot $OutputPath }
        $OutputPath = [System.IO.Path]::GetFullPath($OutputPath)
    }
    # Release the trusted Python launcher only after assigning its job.
    $launcher = 'import sys; sys.stdin.buffer.read(1); import runpy; sys.argv=sys.argv[1:]; runpy.run_path(sys.argv[0], run_name="__main__")'
    $arguments = @('-c', $launcher, (Join-Path $repoRoot 'scripts/windows_ocr_runtime_diagnostics.py'))
    if ($PSBoundParameters.ContainsKey('PdfPath')) { $arguments += @('--pdf', $PdfPath) }
    if ($PSBoundParameters.ContainsKey('DbFile')) { $arguments += @('--db-file', $DbFile) }
    if ($OutputPath) { $arguments += @('--output', $OutputPath) }
    if ($Compact) { $arguments += '--compact' }
    $nativeArguments = (($arguments | ForEach-Object { ConvertTo-NativeArgument $_ }) -join ' ')
    $job = New-Object OcrDiagnosticJob1002
    if ([DateTime]::UtcNow -gt $deadline) { throw 'timeout' }
    $process = $job.Start($python, $nativeArguments, $repoRoot)
    $started = $true
    $job.Input.Close()
    $streams = @($job.Output, $job.Error)
    $buffers = @((New-Object byte[] 4096), (New-Object byte[] 4096))
    $tasks = @($streams[0].ReadAsync($buffers[0], 0, 4096), $streams[1].ReadAsync($buffers[1], 0, 4096))
    $closed = @($false, $false)
    $lengths = @(0, 0)
    $safeOutput = New-Object System.IO.MemoryStream
    while (-not ($closed[0] -and $closed[1] -and $process.HasExited)) {
        if ([DateTime]::UtcNow -gt $deadline) { throw 'timeout' }
        foreach ($index in @(0, 1)) {
            if (-not $closed[$index] -and $tasks[$index].IsCompleted) {
                $count = $tasks[$index].GetAwaiter().GetResult()
                $lengths[$index] += $count
                if ($lengths[$index] -gt 65536) { throw 'output_limit' }
                if ($count -eq 0) { $closed[$index] = $true }
                else {
                    if ($index -eq 0) { $safeOutput.Write($buffers[$index], 0, $count) }
                    $tasks[$index] = $streams[$index].ReadAsync($buffers[$index], 0, 4096)
                }
            }
        }
        Start-Sleep -Milliseconds 10
    }
    $diagnosticExit = if ($process.ExitCode -eq 0) { 0 } else { 1 }
    $utf8 = New-Object System.Text.UTF8Encoding($false, $true)
    if ($OutputPath) {
        if (-not (Test-Path -LiteralPath $OutputPath) -or (Get-Item -LiteralPath $OutputPath).Length -gt 65536) { throw 'protocol_error' }
        $text = [System.IO.File]::ReadAllText($OutputPath, $utf8)
    }
    else { $text = $utf8.GetString($safeOutput.ToArray()) }
    $result = ConvertTo-SafeDiagnostic $text
    if ($diagnosticExit -eq 0) {
        $required = @('runtime_config', 'models', 'runtime_import', 'engine_smoke')
        if ($PSBoundParameters.ContainsKey('PdfPath')) { $required += 'pdf' }
        if ($PSBoundParameters.ContainsKey('DbFile')) { $required += 'database' }
        foreach ($id in $required) {
            $matching = @($result.checks | Where-Object { $_.id -ceq $id -and $_.requirement -ceq 'required' -and $_.status -ceq 'pass' })
            if ($matching.Count -ne 1) { $diagnosticExit = 1 }
        }
        if (@($result.checks | Where-Object { $_.requirement -ceq 'required' -and $_.status -cne 'pass' }).Count -gt 0) { $diagnosticExit = 1 }
    }
    if (-not $OutputPath) { $result | ConvertTo-Json -Depth 5 -Compress:$Compact }
    if ($diagnosticExit -ne 0) { [Console]::Error.WriteLine('OCR diagnostic failed; inspect safe check results.') }
}
catch {
    [Console]::Error.WriteLine('OCR diagnostic wrapper failed (not_completed).')
    $diagnosticExit = 1
}
finally {
    if ($null -ne $job) { $job.Dispose() }
    if ($null -ne $process) {
        if ($started -and -not $process.HasExited) {
            $process.Kill()
            $process.WaitForExit(10000) | Out-Null
        }
        $process.Dispose()
    }
}
exit $diagnosticExit
