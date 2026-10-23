#!/bin/bash
# Runs as root (via com.palace.schedule-wakes) and books a Mac wake 2 minutes
# before each collection run over the next 2 days. Safe to run repeatedly:
# wakes that are already booked are skipped.
# Keep RUN_TIMES in sync with com.palace.collection.plist (Mac local time).
RUN_TIMES="00:00 10:00 11:00 12:00 13:00 14:00 15:00 16:00 17:00 18:00 19:00 20:00 21:00 22:00 23:00"

now=$(date +%s)
booked=$(pmset -g sched)
for day in 0 1 2; do
    d=$(date -v+"${day}"d +%Y-%m-%d)
    for t in $RUN_TIMES; do
        wake=$(( $(date -j -f "%Y-%m-%d %H:%M:%S" "$d $t:00" +%s) - 120 ))
        [ "$wake" -le "$now" ] && continue
        echo "$booked" | grep -q "wake at $(date -r "$wake" "+%m/%d/%Y %H:%M:%S")" && continue
        pmset schedule wake "$(date -r "$wake" "+%m/%d/%y %H:%M:%S")"
    done
done
