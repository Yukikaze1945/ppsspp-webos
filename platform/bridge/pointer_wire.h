/* SPDX-License-Identifier: GPL-3.0-only
 * webOS community adaptation, modified 2026-10-31.
 * Bridge-derived files retain their upstream provenance; see THIRD_PARTY_NOTICES.md.
 */
#pragma once
/* Private PPSSPP v0.0.8 pair: three-word events, unchanged BridgeCtrl ABI. */
#undef INPUT_EVT_MAX
#define INPUT_EVT_MAX 64
#define PP_POINTER_TYPE_MASK 0xf0000000u
#define PP_POINTER_ENTER 0x10000000u
#define PP_POINTER_MOTION 0x20000000u
#define PP_POINTER_BUTTON 0x30000000u
#define PP_POINTER_LEAVE 0x40000000u
#define PP_POINTER_AXIS 0x50000000u
#define PP_POINTER_SLOT(tag) (((tag) >> 8) & 0xffffu)
#define PP_POINTER_SEAT(tag) ((tag) & 0xffu)
