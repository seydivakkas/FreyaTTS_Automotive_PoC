"""M01 structured event demo: no speech, model weights, or SIP traffic."""
import asyncio
import json
from automotive_voice.core.event_bus import EventBus
from automotive_voice.core.session_manager import SessionManager

async def run() -> None:
    bus = EventBus(default_capacity=32)
    observer = await bus.subscribe("local-demo")
    manager = SessionManager(bus)
    await manager.create("example-m01")
    await manager.start("example-m01")
    await manager.begin_turn("example-m01")
    await manager.begin_response("example-m01")
    old_generation_valid_before = await manager.accepts_chunk("example-m01", 1)
    await manager.interrupt("example-m01")
    old_generation_valid_after = await manager.accepts_chunk("example-m01", 1)
    await manager.complete_interrupt("example-m01")
    await manager.end("example-m01")
    count = await manager.dispatch_pending("example-m01")
    envelopes = [observer.get_nowait().to_dict() for _ in range(count)]
    print(json.dumps({"mode": "synthetic-only", "events_published": count,
                      "old_generation_accepted_before": old_generation_valid_before,
                      "old_generation_accepted_after": old_generation_valid_after,
                      "sequence": [e["sequence"] for e in envelopes],
                      "event_types": [e["event_type"] for e in envelopes],
                      "session": "example-m01", "final_state": "ENDED"}, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    asyncio.run(run())
