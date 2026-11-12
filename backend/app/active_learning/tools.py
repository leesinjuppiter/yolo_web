from app.active_learning import manifests, results, review, service

TOOLS = {
    "active_learning.options": service.options,
    "active_learning.iteration_create": service.create_iteration,
    "active_learning.iteration_list": service.list_iterations,
    "active_learning.iteration_detail": service.iteration_detail,
    "active_learning.summary": service.overview,
    "active_learning.start": service.create_task,
    "active_learning.cancel": service.cancel_task,
    "active_learning.list": service.list_tasks,
    "active_learning.status": service.task_status,
    "active_learning.logs": service.task_logs,
    "active_learning.recommend": service.list_candidates,
    "active_learning.candidate_detail": service.candidate_detail,
    "active_learning.select": review.select_candidates,
    "active_learning.add_candidate": review.add_candidates,
    "active_learning.link_reference": review.link_reference,
    "active_learning.review": review.confirm,
    "active_learning.prepare_training": manifests.prepare_training,
    "active_learning.choose_result": results.choose,
    "active_learning.compare": results.comparison,
    "active_learning.complete": results.complete,
}
