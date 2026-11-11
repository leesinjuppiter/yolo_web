from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.notifications.tools import changes

router = APIRouter()


@router.get("/api/changes")
async def subscribe(request: Request):
    return StreamingResponse(changes(request.app.state.change_feed), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"})
