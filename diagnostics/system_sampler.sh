#!/bin/sh
# Read-only, low-overhead sampler for PPSSPP and its app-private GLES proxy.
# Output is tab-delimited tagged records grouped by TS/END blocks.
set -u

DURATION=${1:-30}
INTERVAL=${2:-1}
case "$DURATION:$INTERVAL" in
  *[!0-9:]*|:*) echo "usage: $0 [seconds [interval_seconds]]" >&2; exit 2 ;;
esac
[ "$DURATION" -gt 0 ] && [ "$INTERVAL" -gt 0 ] || {
  echo "duration and interval must be positive integers" >&2
  exit 2
}

APP_ROOT=/media/developer/apps/usr/palm/applications/org.ppsspp.webos
JAIL_APP_ROOT=/var/palm/jail/org.ppsspp.webos/media/developer/apps/usr/palm/applications/org.ppsspp.webos
CLK_TCK=$(getconf CLK_TCK 2>/dev/null || echo 100)
TAB=$(printf '\t')

read_scalar() {
  scalar=
  IFS= read -r scalar < "$1" && return 0
  [ -n "$scalar" ]
}

trim_value() {
  trimmed=$1
  while :; do
    case "$trimmed" in
      ' '*) trimmed=${trimmed# } ;;
      "$TAB"*) trimmed=${trimmed#"$TAB"} ;;
      *) break ;;
    esac
  done
  value=$trimmed
}

classify_exe() {
  candidate_exe=$1
  case "$candidate_exe" in
    "$APP_ROOT/PPSSPPSDL"|"$JAIL_APP_ROOT/PPSSPPSDL") role=app ;;
    "$APP_ROOT/service/gles_proxy"|"$JAIL_APP_ROOT/service/gles_proxy") role=proxy ;;
    *) return 1 ;;
  esac
  return 0
}

sample_system() {
  if IFS=' ' read -r uptime idle </proc/uptime 2>/dev/null; then
    printf 'UPTIME\t%s\t%s\n' "$uptime" "$idle"
  fi
  if IFS= read -r line </proc/loadavg 2>/dev/null; then
    printf 'LOADAVG\t%s\n' "$line"
  fi
  if [ -r /proc/stat ]; then
    while IFS= read -r line; do
      case "$line" in
        cpu\ *|cpu[0-9]*|ctxt\ *|processes\ *|procs_running\ *|procs_blocked\ *)
          printf 'STAT\t%s\n' "$line" ;;
      esac
    done </proc/stat
  fi
  if [ -r /proc/vmstat ]; then
    while IFS=' ' read -r key value rest; do
      case "$key" in
        pswpin|pswpout|pgfault|pgmajfault|pgscan_kswapd*|pgscan_direct*|pgsteal_kswapd*|pgsteal_direct*)
          printf 'VMSTAT\t%s\t%s\n' "$key" "$value" ;;
      esac
    done </proc/vmstat
  fi
  if [ -r /proc/meminfo ]; then
    while IFS= read -r line; do
      key=${line%%:*}
      case "$key" in
        MemTotal|MemFree|MemAvailable|Buffers|Cached|SwapTotal|SwapFree|SwapCached|Active|Inactive|Dirty|Writeback)
          trim_value "${line#*:}"
          printf 'MEMINFO\t%s\t%s\n' "$key" "$value" ;;
      esac
    done </proc/meminfo
  fi
  if IFS= read -r value </sys/devices/system/cpu/online 2>/dev/null; then
    printf 'CPU_ONLINE\t%s\n' "$value"
  fi

  for cpu_dir in /sys/devices/system/cpu/cpu[0-9]*; do
    [ -d "$cpu_dir" ] || continue
    cpu=${cpu_dir##*/}
    cpu=${cpu#cpu}
    for attr in scaling_cur_freq cpuinfo_cur_freq scaling_min_freq scaling_max_freq cpuinfo_min_freq cpuinfo_max_freq; do
      path="$cpu_dir/cpufreq/$attr"
      if [ -r "$path" ] && read_scalar "$path"; then
        value=$scalar
        printf 'FREQ\t%s\t%s\t%s\n' "$cpu" "$attr" "$value"
      fi
    done
  done
  for devfreq_dir in /sys/class/devfreq/*; do
    [ -d "$devfreq_dir" ] || continue
    device=${devfreq_dir##*/}
    for attr in cur_freq min_freq max_freq; do
      path="$devfreq_dir/$attr"
      if [ -r "$path" ] && read_scalar "$path"; then
        value=$scalar
        printf 'DEVFREQ\t%s\t%s\t%s\n' "$device" "$attr" "$value"
      fi
    done
  done

  thermal_found=0
  for zone_dir in /sys/class/thermal/thermal_zone[0-9]*; do
    [ -d "$zone_dir" ] || continue
    thermal_found=1
    zone=${zone_dir##*/}
    type=unknown
    temp=unknown
    [ -r "$zone_dir/type" ] && read_scalar "$zone_dir/type" && type=$scalar
    [ -r "$zone_dir/temp" ] && read_scalar "$zone_dir/temp" && temp=$scalar
    printf 'THERMAL\t%s\t%s\t%s\n' "$zone" "$type" "$temp"
  done
  [ "$thermal_found" -eq 1 ] || printf 'THERMAL_NONE\t/sys/class/thermal/thermal_zone*\n'

  # /proc/lg/pm/status is read-only text telemetry and includes the current
  # governor, CPU count/load, clock and temperature. Do not read reg_rd/MMIO.
  if [ -r /proc/lg/pm/status ]; then
    lgpm_status=$(cat /proc/lg/pm/status 2>/dev/null)
    while IFS= read -r line; do
      case "$line" in
        governor:*|cpu_num:*|load:*|loadavg:*|freq:*|*"CPU TEMP["*"]'C"*)
          key=${line%%:*}
          if [ "$key" = "$line" ]; then
            key=cpu_temperature
            rest=${line#*CPU TEMP[}
            value=${rest%%]*}
          else
            value=${line#*:}
            trim_value "$value"
          fi
          printf 'LGPM\t%s\t%s\n' "$key" "$value" ;;
      esac
    done <<EOF_LGPM
$lgpm_status
EOF_LGPM
  fi
}

sample_task() {
  owner_pid=$1
  task_dir=$2
  task_tid=${task_dir##*/}
  [ -r "$task_dir/stat" ] || return 0
  IFS= read -r task_stat < "$task_dir/stat" || return 0
  printf 'TASK\t%s\t%s\t%s\n' "$owner_pid" "$task_tid" "$task_stat"
  if [ -r "$task_dir/comm" ] && IFS= read -r task_comm < "$task_dir/comm"; then
    printf 'TASKCOMM\t%s\t%s\t%s\n' "$owner_pid" "$task_tid" "$task_comm"
  fi
  if [ -r "$task_dir/wchan" ] && IFS= read -r task_wchan < "$task_dir/wchan"; then
    printf 'WCHAN\t%s\t%s\t%s\n' "$owner_pid" "$task_tid" "$task_wchan"
  fi
  if [ -r "$task_dir/schedstat" ] && IFS= read -r task_schedstat < "$task_dir/schedstat"; then
    printf 'SCHEDSTAT\t%s\t%s\t%s\n' "$owner_pid" "$task_tid" "$task_schedstat"
  fi
}

sample_process() {
  sampled_pid=$1
  sampled_role=$2
  sampled_exe=$3
  sampled_dir=/proc/$sampled_pid
  [ -r "$sampled_dir/stat" ] || return 0
  IFS= read -r proc_stat < "$sampled_dir/stat" || return 0
  printf 'PROC\t%s\t%s\t%s\t%s\n' "$sampled_pid" "$sampled_role" "$sampled_exe" "$proc_stat"

  if [ -r "$sampled_dir/status" ]; then
    while IFS= read -r line; do
      key=${line%%:*}
      case "$key" in
        Name|State|Threads|VmRSS|VmHWM|VmSwap|voluntary_ctxt_switches|nonvoluntary_ctxt_switches)
          trim_value "${line#*:}"
          printf 'STATUS\t%s\t%s\t%s\n' "$sampled_pid" "$key" "$value" ;;
      esac
    done < "$sampled_dir/status"
  fi

  for task_dir in "$sampled_dir"/task/[0-9]*; do
    [ -d "$task_dir" ] || continue
    sample_task "$sampled_pid" "$task_dir"
  done
}

sample_number=0
while [ "$sample_number" -lt "$DURATION" ]; do
  IFS=' ' read -r uptime idle </proc/uptime 2>/dev/null || uptime=unknown
  printf 'TS\t%s\n' "$uptime"
  printf 'CLK_TCK\t%s\n' "$CLK_TCK"
  sample_system

  for proc_dir in /proc/[0-9]*; do
    [ -d "$proc_dir" ] || continue
    pid=${proc_dir##*/}
    [ -r "$proc_dir/comm" ] || continue
    IFS= read -r comm < "$proc_dir/comm" || continue
    case "$comm" in
      PPSSPPSDL|gles_proxy) ;;
      *) continue ;;
    esac
    exe=$(readlink "$proc_dir/exe" 2>/dev/null) || continue
    classify_exe "$exe" || continue
    sample_process "$pid" "$role" "$exe"
  done

  printf 'END\n'
  sample_number=$((sample_number + 1))
  [ "$sample_number" -lt "$DURATION" ] && sleep "$INTERVAL"
done
