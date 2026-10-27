# One native observation of the existing Industrial UI pytest shard. Never retry.
set pagination off
set confirm off
set disable-randomization off
set startup-with-shell off
# GDB injects terminal dimensions even in batch mode; the CI shell has neither.
unset environment LINES
unset environment COLUMNS
run
if !$_isvoid($_exitcode)
  quit $_exitcode
end

# A stopped inferior is not a successful pytest exit. Keep stacks finite in depth.
info program
thread apply all bt 20
set $industrial_exit = 1
set $industrial_signal = 0
if !$_isvoid($_exitsignal)
  set $industrial_signal = $_exitsignal
else
  if !$_isvoid($_siginfo)
    set $industrial_signal = $_siginfo.si_signo
  end
end
if $industrial_signal > 0 && $industrial_signal < 128
  set $industrial_exit = 128 + $industrial_signal
end
quit $industrial_exit
