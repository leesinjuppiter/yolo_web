from app.dataset import service
from app.dataset.exchange.tools import EXCHANGE_TOOLS

TOOLS = {
    "dataset.list": service.list_datasets,
    "dataset.summary": service.dataset_summary,
    "dataset.create": service.create_dataset,
    "dataset.delete": service.delete_dataset,
    "dataset.add_images": service.upload_images,
    "dataset.delete_image": service.delete_image,
    "dataset.update_splits": service.update_splits,
    "dataset.update_class": service.update_class,
    "annotation.save": service.save_annotations,
    **EXCHANGE_TOOLS,
}
