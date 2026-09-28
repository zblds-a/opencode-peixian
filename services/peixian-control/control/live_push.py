"""Post-commit delivery of verified answer content and run progress onto account event hubs.

Notices are only ever built from durable, already-verified data (source segments,
platform-rendered answer sections, run phases); unverified model text never passes here.
"""
import asyncio
import json

VERSION = 'live-push-v1'
# The browser SSE reader rejects a single event above 256 KiB; SSE frames are ASCII-escaped JSON.
MAX_EVENT_TEXT = 192 * 1024
PHASES = {
    'pending_dispatch': ('queued', '已受理，正在排队'),
    'dispatching': ('queued', '已受理，正在排队'),
    'generating': ('thinking', '正在分析问题'),
    'waiting_question': ('waiting_question', '等待补充查询条件'),
    'waiting_permission': ('waiting_permission', '等待授权确认'),
    'confirming_admission': ('reconciling', '正在确认执行状态'),
    'confirming_state': ('reconciling', '正在确认执行状态'),
    'recovery_required': ('reconciling', '正在确认执行状态'),
    'stopping': ('cancelling', '正在停止'),
}
TERMINAL = {'completed': '已完成', 'failed': '执行未完成', 'cancelled': '已停止'}

_target = {}


def install(loop, hubs):
    _target.update(loop=loop, hubs=hubs)


def uninstall():
    _target.clear()


def push(uid, notice):
    loop, hubs = _target.get('loop'), _target.get('hubs')
    if loop is None or hubs is None or loop.is_closed():
        return

    def deliver():
        hub = hubs.hubs.get(uid)
        if hub is not None and not hub.closed:
            hub.publish(notice)

    try:
        running = asyncio.get_running_loop()
    except RuntimeError:
        running = None
    try:
        if running is loop:
            deliver()
        else:
            loop.call_soon_threadsafe(deliver)
    except RuntimeError:
        pass


def after_commit(store, uid, notice):
    store.after_commit(lambda: push(uid, notice))


def segment_notice(row, message_id, segment, *, final=False):
    notice = {'type': 'answer.segment', 'version': VERSION, 'session_id': row['session_id'], 'run_id': row['id'],
              'message_id': message_id, 'part_id': segment['part_id'], 'sequence': segment['sequence'],
              'display_kind': segment['display_kind'], 'origin': segment['origin'], 'final': final}
    for key in ('index', 'count'):
        if key in segment:
            notice[key] = segment[key]
    if len(json.dumps(segment['text'])) > MAX_EVENT_TEXT:
        notice['truncated'] = True
    else:
        notice['text'] = segment['text']
    return notice


def progress_notice(row, phase, label, status=None):
    notice = {'type': 'run.progress', 'version': VERSION, 'session_id': row['session_id'], 'run_id': row['id'],
              'phase': phase, 'label': label}
    if status:
        notice['status'] = status
    return notice


def phase_notice(row, status, phase):
    if status in TERMINAL:
        return progress_notice(row, status, TERMINAL[status], status)
    mapped = PHASES.get(phase)
    if not mapped:
        return None
    return progress_notice(row, mapped[0], mapped[1], status)
