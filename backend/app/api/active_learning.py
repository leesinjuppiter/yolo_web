from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy.orm import Session

from app.active_learning import schemas
from app.active_learning.tools import TOOLS
from app.core.database import get_db

router = APIRouter(prefix="/api/active-learning", tags=["active-learning"])
Database = Annotated[Session, Depends(get_db)]
Page = Annotated[int, Query(ge=1)]
Size = Annotated[int, Query(ge=1, le=100)]


@router.get("/options")
def options(db: Database):
    return TOOLS["active_learning.options"](db)


@router.get("/overview")
def overview(db: Database):
    return TOOLS["active_learning.summary"](db)


@router.get("/iterations")
def iterations(db: Database, page: Page = 1, page_size: Size = 20, query: str = "", status: str | None = None):
    return TOOLS["active_learning.iteration_list"](db, page, page_size, query, status)


@router.post("/iterations", status_code=201)
def create_iteration(request: schemas.IterationRequest, db: Database):
    return TOOLS["active_learning.iteration_create"](db, request)


@router.get("/iterations/{identifier}")
def iteration(identifier: UUID, db: Database):
    return TOOLS["active_learning.iteration_detail"](db, str(identifier))


@router.get("/tasks")
def tasks(db: Database, page: Page = 1, page_size: Size = 20, status: str | None = None,
          iterationId: UUID | None = None, query: Annotated[str, Query(max_length=120)] = ""):
    return TOOLS["active_learning.list"](db, page, page_size, status, iterationId, query)


@router.post("/tasks", status_code=202)
def create_task(request: schemas.RecommendationRequest, db: Database,
                key: Annotated[str | None, Header(alias="Idempotency-Key")] = None):
    return TOOLS["active_learning.start"](db, request, key)


@router.get("/tasks/{identifier}")
def task(identifier: UUID, db: Database):
    return TOOLS["active_learning.status"](db, str(identifier))


@router.get("/tasks/{identifier}/logs")
def logs(identifier: UUID, db: Database, after_sequence: Annotated[int, Query(ge=0)] = 0):
    return TOOLS["active_learning.logs"](db, str(identifier), after_sequence)


@router.post("/tasks/{identifier}/cancel")
def cancel(identifier: UUID, db: Database):
    return TOOLS["active_learning.cancel"](db, str(identifier))


@router.get("/tasks/{identifier}/candidates")
def candidates(identifier: UUID, db: Database, page: Page = 1, page_size: Size = 30,
               purpose: str | None = None, selected: bool | None = None,
               reason: str | None = None, review_state: str | None = None):
    return TOOLS["active_learning.recommend"](db, str(identifier), page, page_size, purpose,
                                             selected, reason, review_state)


@router.get("/candidates/{identifier}")
def candidate(identifier: UUID, db: Database):
    return TOOLS["active_learning.candidate_detail"](db, str(identifier))


@router.post("/iterations/{identifier}/selection")
def selection(identifier: UUID, request: schemas.SelectionRequest, db: Database):
    return TOOLS["active_learning.select"](db, str(identifier), request)


@router.post("/iterations/{identifier}/candidates")
def add(identifier: UUID, request: schemas.AddCandidatesRequest, db: Database):
    return TOOLS["active_learning.add_candidate"](db, str(identifier), request)


@router.post("/candidates/{identifier}/references")
def references(identifier: UUID, request: schemas.ReferencesRequest, db: Database):
    return TOOLS["active_learning.link_reference"](db, str(identifier), request)


@router.get("/iterations/{identifier}/review-queue")
def review_queue(identifier: UUID, db: Database, page: Page = 1, page_size: Size = 30):
    return TOOLS["active_learning.recommend"](db, str(identifier), page, page_size, queue=True)


@router.post("/candidates/{identifier}/review")
def review(identifier: UUID, request: schemas.ReviewRequest, db: Database):
    return TOOLS["active_learning.review"](db, str(identifier), request)


@router.post("/iterations/{identifier}/prepare-training")
def prepare(identifier: UUID, db: Database):
    return TOOLS["active_learning.prepare_training"](db, str(identifier))


@router.post("/iterations/{identifier}/result")
def choose_result(identifier: UUID, request: schemas.ResultRequest, db: Database):
    return TOOLS["active_learning.choose_result"](db, str(identifier), request)


@router.get("/iterations/{identifier}/comparison")
def comparison(identifier: UUID, db: Database):
    return TOOLS["active_learning.compare"](db, str(identifier))


@router.post("/iterations/{identifier}/complete")
def complete(identifier: UUID, db: Database):
    return TOOLS["active_learning.complete"](db, str(identifier))
