from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.dataset.repository import Conflict, NotFound
from app.deployment.models import DeploymentPackage
from app.deployment.builder import requirement_versions
from app.model_exports import service as exports
from app.model_exports.schemas import PackageRequest
from app.model_exports.storage import digest, package_dir
from app.models.sources import registered_asset


def get_package(db: Session, package_id: str) -> DeploymentPackage:
    row = db.get(DeploymentPackage, package_id)
    if row is None:
        raise NotFound("部署包不存在")
    return row


def response(row: DeploymentPackage) -> dict:
    return {"id": row.id, "exportId": row.export_id, "status": row.status, "phase": row.phase,
            "manifest": row.manifest, "error": row.error, "logs": row.logs,
            "createdAt": row.created_at, "startedAt": row.started_at, "finishedAt": row.finished_at,
            "downloadUrl": f"/api/deployment-packages/{row.id}/download" if row.status == "succeeded" else None}


def create(db: Session, request: PackageRequest, key: str | None) -> dict:
    with db.begin():
        if key:
            db.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(f"package:{key}", 0))))
            existing = db.scalar(select(DeploymentPackage).where(DeploymentPackage.idempotency_key == key))
            if existing:
                if existing.export_id != str(request.exportId):
                    raise Conflict("幂等键已用于其他部署包")
                return response(existing)
        exports.download(db, str(request.exportId))
        export = exports.get_task(db, str(request.exportId))
        try:
            requirement_versions(export.report or {})
        except ValueError as exc:
            raise Conflict(str(exc)) from exc
        version, _, _, _ = registered_asset(db, export.version_id)
        if version.lifecycle == "archived":
            raise Conflict("归档模型不能创建新的部署包")
        row = DeploymentPackage(export_id=str(request.exportId), idempotency_key=key)
        db.add(row)
        db.flush()
        return response(row)


def overview(db: Session, page: int, page_size: int) -> dict:
    rows = db.scalars(select(DeploymentPackage).order_by(DeploymentPackage.created_at.desc())
                      .offset((page-1)*page_size).limit(page_size))
    return {"items": [response(row) for row in rows],
            "total": db.scalar(select(func.count()).select_from(DeploymentPackage)), "page": page, "pageSize": page_size}


def detail(db: Session, package_id: str) -> dict:
    return response(get_package(db, package_id))


def download(db: Session, package_id: str):
    row = get_package(db, package_id)
    path = package_dir(package_id) / "deployment-package.zip"
    if row.status != "succeeded" or not path.is_file():
        raise Conflict("部署包尚未完成或文件丢失")
    if digest(path) != row.manifest["packageSha256"]:
        raise Conflict("部署包校验失败")
    return path


TOOLS = {"deployment.package_build": create, "deployment.package_list": overview,
         "deployment.package_detail": detail, "deployment.package_download": download}
