#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-only
# Community build/packaging adaptation, 2026-10-31.
set -eu
luna-send -n 1 luna://com.webos.applicationManager/launch '{"id":"org.ppsspp.webos"}'
