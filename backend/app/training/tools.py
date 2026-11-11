from app.training import repository, service

TOOLS = {
    "training.options": service.options,
    "training.preflight": service.preflight,
    "training.datasets": service.datasets,
    "training.start": service.create,
    "training.list": service.overview,
    "training.status": service.status,
    "training.cancel": service.cancel,
    "training.resume": service.resume,
    "training.delete": service.delete,
    "training.logs": service.logs,
    "training.export_log": repository.export_log,
    "training.resources": service.resources,
    "training.metrics": service.metrics,
    "training.latest_result": service.latest_result,
    "training.diagnose_failure": service.diagnose_failure,
    "training.download_artifact": service.download,
    "model.register_training_version": service.register_version,
}

