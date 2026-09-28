"""Single-loop, account-scoped readers. Queues carry notices plus verified answer segments, never model text."""
import asyncio
from contextlib import suppress
import json
import random
import time

import httpx
from fastapi import HTTPException

from .store import ident


RESYNC = {"type": "resync_required"}
COALESCE_SECONDS = .15


class Subscriber:
    def __init__(self, hub, reservation, authorize):
        self.hub, self.reservation, self.authorize = hub, reservation, authorize
        self.queue = asyncio.Queue(hub.manager.config["hub_queue"])
        self.pending = set()
        self.closed = False

    def put(self, notice):
        if self.closed:
            return
        # Equal pending notifications can be merged without losing a resource.
        key = json.dumps(notice, sort_keys=True)
        if key in self.pending:
            return
        if self.queue.full():
            while not self.queue.empty():
                self.queue.get_nowait()
            self.pending.clear()
            self.hub.manager.overflow += 1
            self.queue.put_nowait(RESYNC)
            self.pending.add(json.dumps(RESYNC, sort_keys=True))
            return
        self.queue.put_nowait(notice)
        self.pending.add(key)

    async def close(self, retain=False):
        if self.closed:
            return
        self.closed = True
        self.hub.subscribers.pop(self.reservation.id, None)
        while not self.queue.empty():
            self.queue.get_nowait()
        self.pending.clear()
        self.queue.put_nowait(None)
        if not self.hub.subscribers:
            retain = retain and self.hub.manager.config["hub_retention_seconds"] > 0
            self.hub.retainer = self.authorize if retain else None
            if retain and not self.hub.closed:
                self.hub.start_retention()
            if not retain:
                await self.hub.close("last_subscription_closed")

    async def body(self):
        yield b'event: change\ndata: {"type":"connected"}\n\n'
        while not self.closed:
            try:
                notice = await asyncio.wait_for(self.queue.get(), self.hub.manager.config["sse_heartbeat_seconds"])
            except TimeoutError:
                yield b": heartbeat\n\n"
                continue
            if notice is None:
                return
            self.pending.discard(json.dumps(notice, sort_keys=True))
            yield ("event: change\ndata: " + json.dumps(notice, separators=(",", ":")) + "\n\n").encode()


class AccountHub:
    def __init__(self, manager, uid):
        self.manager, self.uid = manager, uid
        self.id = ident()
        self.subscribers = {}
        self.response = None
        self.task = None
        self.ready = asyncio.get_running_loop().create_future()
        self.closed = False
        self.absent_since = None
        self.retainer = None
        self.identity = None
        self.retention_generation = 0
        self.deadline_handle = None
        self.cleanup_task = None
        self.coalescing = {}

    def invalidate_retention(self):
        self.retention_generation += 1
        self.absent_since = None
        self.retainer = None
        if self.deadline_handle is not None:
            self.deadline_handle.cancel()
            self.deadline_handle = None

    def start_retention(self):
        self.retention_generation += 1
        generation = self.retention_generation
        self.absent_since = time.monotonic()
        if self.deadline_handle is not None:
            self.deadline_handle.cancel()
        def expire():
            if self.retention_current(generation):
                self.begin_close("retention_expired")
        self.deadline_handle = asyncio.get_running_loop().call_later(
            self.manager.config["hub_retention_seconds"], expire)

    def retention_current(self, generation):
        return (not self.closed and not self.subscribers and self.absent_since is not None
                and generation == self.retention_generation)

    async def check_retention(self, binding):
        generation = self.retention_generation
        if not self.retention_current(generation):
            return False
        try:
            if self.retainer is None:
                return True
            await asyncio.wait_for(self.retainer(), 2)
        except (HTTPException, TimeoutError):
            return self.retention_current(generation)
        if not self.retention_current(generation):
            return False
        if time.monotonic() - self.absent_since < self.manager.config["hub_idle_seconds"]:
            return False
        try:
            active = await self.manager.active(binding)
        except Exception:
            active = True  # Unknown may retain only until the independent deadline.
        return self.retention_current(generation) and not active

    def publish(self, notice):
        # Repeated resource notices within one window collapse into the first plus one trailing copy.
        # Content-bearing notices (answer.segment, run.progress, run.updated) are never delayed.
        window = self.manager.config.get("hub_coalesce_seconds", COALESCE_SECONDS)
        if notice.get("type") != "updated" or window <= 0:
            self.deliver(notice)
            return
        key = json.dumps(notice, sort_keys=True)
        if key in self.coalescing:
            self.coalescing[key] = True
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self.deliver(notice)
            return
        self.deliver(notice)
        self.coalescing[key] = False
        loop.call_later(window, self.release, key, notice)

    def release(self, key, notice):
        if self.coalescing.pop(key, False) and not self.closed:
            self.deliver(notice)

    def deliver(self, notice):
        for subscriber in tuple(self.subscribers.values()):
            subscriber.put(notice)

    def begin_close(self, reason):
        if self.closed:
            return
        self.closed = True
        self.invalidate_retention()
        if not self.ready.done():
            self.ready.set_result(False)
        if self.task is not None and self.task is not asyncio.current_task():
            self.task.cancel()
        self.cleanup_task = asyncio.create_task(self.finish_close(reason))

    async def close(self, reason):
        self.begin_close(reason)
        if asyncio.current_task() is self.task:
            return  # Cleanup joins the reader, never the other way round.
        await asyncio.shield(self.cleanup_task)

    async def finish_close(self, reason):
        # Keep the account registered until the reader has actually terminated.
        if self.task is not None:
            await asyncio.gather(self.task, return_exceptions=True)
        for subscriber in tuple(self.subscribers.values()):
            subscriber.closed = True
            while not subscriber.queue.empty():
                subscriber.queue.get_nowait()
            subscriber.pending.clear()
            subscriber.queue.put_nowait(None)
            runner = subscriber.reservation.runner
            if runner is not None and runner is not asyncio.current_task():
                runner.cancel()
        self.subscribers.clear()
        if self.manager.hubs.get(self.uid) is self:
            self.manager.hubs.pop(self.uid)
        self.manager.closed_count += 1
        self.manager.reasons[reason] = self.manager.reasons.get(reason, 0) + 1

    async def cleanup_stream(self, pending, iterator):
        try:
            if pending is not None:
                pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)
            if iterator is not None:
                await iterator.aclose()
        finally:
            if self.response is not None:
                with suppress(Exception):
                    await asyncio.wait_for(self.response.aclose(), 1)
                self.response = None
            self.manager.cache.release(self.uid, self.id)

    async def run(self):
        from .streams import _events, change_notice, _open_response
        attempt = 0
        try:
            while not self.closed:
                binding = await self.manager.binding(self.uid)
                if self.closed:
                    return
                if self.manager.cache.acquire_result(self.uid, self.id) not in ("acquired", "renewed"):
                    break
                pending = None
                iterator = None
                try:
                    request = self.manager.client.build_request("GET", binding["base"] + "/global/event",
                        headers=binding["headers"], timeout=httpx.Timeout(None, connect=4, write=4, pool=1))
                    self.response = await asyncio.wait_for(_open_response(self.manager.client, request, self), 4)
                    if self.closed:
                        return
                    if self.response.status_code != 200:
                        raise httpx.RemoteProtocolError("Event upstream unavailable")
                    self.identity = binding["identity"]
                    if not self.ready.done():
                        self.ready.set_result(True)
                    else:
                        self.publish(RESYNC)
                    iterator = _events(self.response).__aiter__()
                    pending = asyncio.create_task(iterator.__anext__())
                    checked = time.monotonic()
                    renewed = checked
                    opened = checked
                    while not self.closed:
                        done, _ = await asyncio.wait((pending,), timeout=min(.25, self.manager.config["auth_recheck_seconds"]))
                        if self.closed:
                            return
                        current = time.monotonic()
                        if self.manager.cache.take_resync(self.uid, self.id):
                            self.publish(RESYNC)
                        if current - checked >= self.manager.config["auth_recheck_seconds"]:
                            fresh = await self.manager.binding(self.uid)
                            if fresh["identity"] != self.identity:
                                self.publish(RESYNC)
                                break
                            checked = current
                            if await self.check_retention(binding):
                                return
                        if self.closed:
                            return
                        if current - renewed >= self.manager.config["sse_renew_seconds"]:
                            ownership = self.manager.cache.acquire_result(self.uid, self.id)
                            if ownership not in ("acquired", "renewed"):
                                return
                            if ownership == "acquired":
                                self.publish(RESYNC)
                            renewed = current
                        if not done:
                            continue
                        try:
                            envelope = pending.result()
                        except StopAsyncIteration:
                            break
                        pending = asyncio.create_task(iterator.__anext__())
                        await self.manager.observe(self.uid, envelope, self.id) if self.manager.observe else self.manager.cache.observe(self.uid, envelope, self.id)
                        notice = change_notice(envelope)
                        if notice is not None:
                            self.publish(notice)
                        if current - opened > 30:
                            attempt = 0
                except (httpx.HTTPError, ValueError, TimeoutError):
                    if not self.ready.done():
                        self.ready.set_result(False)
                        return
                finally:
                    cleanup = asyncio.create_task(self.cleanup_stream(pending, iterator))
                    try:
                        await asyncio.shield(cleanup)
                    except asyncio.CancelledError:
                        # Expiry during an existing EOF/error cleanup must not orphan it.
                        await asyncio.shield(cleanup)
                        raise
                if self.closed:
                    return
                self.publish(RESYNC)
                self.manager.reconnects += 1
                await asyncio.sleep(min(2 ** min(attempt, 5), self.manager.config["hub_reconnect_seconds"]) + random.random() * .2)
                attempt += 1
        except (HTTPException, TimeoutError):
            pass  # Revocation, maintenance, or unknown binding fails closed.
        finally:
            await self.close("reader_closed")


class AccountEventHubs:
    def __init__(self, client, cache, config, binding, active, *, maximum):
        self.client, self.cache, self.config = client, cache, config
        self.binding, self.active = binding, active
        self.maximum = min(maximum, config["sse_owners"], config["sse_viewers"])
        self.hubs = {}
        self.stopped = False
        self.created = self.closed_count = self.reconnects = self.overflow = 0
        self.reasons = {}
        self.observe = None

    async def subscribe(self, reservation, authorize):
        uid = reservation.uid
        if self.stopped:
            raise HTTPException(503, "实时服务正在关闭", headers={"Retry-After": "2"})
        hub = self.hubs.get(uid)
        if hub is None:
            # No awaits between capacity check and insertion: single-loop atomic.
            if len(self.hubs) >= self.maximum:
                idle = next((value for value in self.hubs.values() if not value.subscribers), None)
                if idle is None:
                    raise HTTPException(503, "实时连接暂时繁忙", headers={"Retry-After": "2"})
                idle.begin_close("capacity_pressure")
                done, _ = await asyncio.wait((idle.cleanup_task,), timeout=min(1, self.config["hub_shutdown_seconds"]))
                if not done:
                    raise HTTPException(503, "实时连接正在清理，请稍后重试", headers={"Retry-After": "2"})
                idle.cleanup_task.result()
                return await self.subscribe(reservation, authorize)
            hub = AccountHub(self, uid)
            self.hubs[uid] = hub
            self.created += 1
        if hub.closed:
            raise HTTPException(503, "实时连接正在清理，请稍后重试", headers={"Retry-After": "2"})
        subscriber = Subscriber(hub, reservation, authorize)
        reservation.subscription = subscriber
        hub.subscribers[reservation.id] = subscriber
        hub.invalidate_retention()
        if hub.task is None:
            hub.task = asyncio.create_task(hub.run())
        try:
            ready = await asyncio.wait_for(asyncio.shield(hub.ready), 4.2)
            if not ready or hub.closed or reservation.closed:
                raise HTTPException(503, "实时连接暂时不可用，请稍后重试", headers={"Retry-After": "2"})
            return subscriber
        except BaseException:
            await subscriber.close()
            raise

    def stop(self):
        self.stopped = True
        for hub in tuple(self.hubs.values()):
            hub.begin_close("shutdown")

    async def close(self):
        self.stop()
        await asyncio.wait_for(asyncio.gather(*(hub.close("shutdown") for hub in tuple(self.hubs.values()))),
                               self.config["hub_shutdown_seconds"])

    def stats(self):
        return {"hubs": len(self.hubs), "upstreams": sum(h.response is not None for h in self.hubs.values()),
            "subscribers": sum(len(h.subscribers) for h in self.hubs.values()),
            "retained": sum(not h.subscribers and not h.closed for h in self.hubs.values()),
            "closing": sum(h.closed for h in self.hubs.values()), "created": self.created,
            "closed": self.closed_count, "reconnects": self.reconnects, "overflows": self.overflow,
            "close_reasons": dict(self.reasons)}


def runtime_binding(app, uid):
    store = app.state.store
    with store.read(snapshot=True) as db:
        row = db.execute("SELECT r.*,u.active,u.must_change,u.auth_version FROM runtimes r JOIN users u ON u.id=r.uid WHERE r.uid=?", (uid,)).fetchone()
        mode = db.execute("SELECT maintenance_mode FROM platform_state WHERE id=1").fetchone()[0]
        if (row is None or not row["active"] or row["must_change"] or row["security_blocked"]
                or row["recovery_required"] or row["status"] not in ("ready", "updating", "draining") or mode != "normal"):
            raise HTTPException(409, "环境暂时受限，请稍后重试")
        return {"base": f"http://px-{row['id']}-gateway:8080",
            "headers": {"X-Peixian-Key": store.decrypt(row["spec"])["gateway_key"]},
            "identity": (row["id"], row["gateway_boot_id"], row["relay_boot_id"], row["revision"], row["authorization_version"], row["auth_version"])}


def create_hubs(app, maximum):
    async def binding(uid):
        return await asyncio.wait_for(app.state.db_work.run(runtime_binding, app, uid), 2)
    async def active(value):
        try:
            response = await app.state.http.get(value["base"] + "/internal/runtime/state", headers=value["headers"], timeout=1)
            response.raise_for_status()
            state = response.json()
            activity = state.get("activity") or {}
            relay = (state.get("relay") or {}).get("activity") or {}
            return not (activity.get("complete") is True and activity.get("idle") is True
                        and relay.get("complete") is True and relay.get("idle") is True)
        except (httpx.HTTPError, ValueError):
            return True  # Unknown may retain briefly, never beyond the hard TTL.
    hubs=AccountEventHubs(app.state.stream_http, app.state.live_text, app.state.limits, binding, active, maximum=maximum)
    from .controlled_answer import observe
    async def guarded(uid,envelope,stream_id):
        await observe(app,uid,envelope,stream_id)
    hubs.observe=guarded
    return hubs
