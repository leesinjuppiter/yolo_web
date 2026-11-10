from app.training import service

TOOLS = {
    "training.options": service.options,
    "training.preflight": service.preflight,
    "training.start": service.create,
    "training.list": service.overview,
    "training.status": service.status,
    "training.cancel": service.cancel,
    "training.logs": service.logs,
    "training.metrics": service.metrics,
    "training.latest_result": service.latest_result,
    "training.diagnose_failure": service.diagnose_failure,
    "training.download_artifact": service.download,
    "model.register_training_version": service.register_version,
}

