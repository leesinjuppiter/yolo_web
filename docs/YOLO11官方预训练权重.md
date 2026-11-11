# YOLO11 官方预训练权重接入

入口：模型训练 → 新建训练任务 → 选择任务类型 → 使用已有权重微调 → 基底模型。

本次下载 Ultralytics 官方 assets 仓库 v8.4.0 发布中现有四类任务的 n/s/m/l/x 权重，共20份、855,866,542字节（约816.2MiB）。没有将权重文件提交到Git。

| 任务 | 下拉框文件名 | 官方预训练数据 |
|---|---|---|
| 目标检测 | yolo11n.pt / yolo11s.pt / yolo11m.pt / yolo11l.pt / yolo11x.pt | COCO |
| 实例分割 | yolo11n-seg.pt / yolo11s-seg.pt / yolo11m-seg.pt / yolo11l-seg.pt / yolo11x-seg.pt | COCO |
| 旋转框 | yolo11n-obb.pt / yolo11s-obb.pt / yolo11m-obb.pt / yolo11l-obb.pt / yolo11x-obb.pt | DOTAv1 |
| 图像分类 | yolo11n-cls.pt / yolo11s-cls.pt / yolo11m-cls.pt / yolo11l-cls.pt / yolo11x-cls.pt | ImageNet |

来源：[Ultralytics YOLO11官方模型说明](https://docs.ultralytics.com/models/yolo11/)、[Ultralytics assets v8.4.0](https://github.com/ultralytics/assets/releases/tag/v8.4.0)。发布中包含多个模型系列，本次仅下载文件名为YOLO11的20份既定资产。

## 存储与校验

服务器存储：/hy-tmp/codex-yolo-20261111/weights。API和训练执行器均使用既有 WORKBENCH_TRAINING_WEIGHTS_DIR 指向该目录。

同目录 official-yolo11.json 记录官方URL、任务类型、官方发布SHA-256、大小、预训练数据集、实际CPU加载和前向检查。仓库记录位于 validation-2026-11-12/official-yolo11.json，只有元数据。

下载先写.pt.part临时文件，核对官方发布大小及SHA-256后原子改名。20份均使用当前Ultralytics加载，核对任务类型，CPU上以1×3×64×64张量执行前向，输出有限性通过。训练执行器复制模型到任务目录时会再次核对清单中的预期哈希。

后端只枚举已存在的四类任务及五种规模的固定文件名，未下载的文件不会提供为选项；未在官方清单中的已有本地权重仍标明“本地预训练”。原有从零训练结构及已注册模型版本来源继续可用。

## 验证范围

- 模型目录/训练执行/API相关回归：33项通过。
- 本地和服务器前端类型检查及构建通过。
- 浏览器确认检测任务可选择yolo11s.pt；切换OBB后只出现匹配的OBB官方权重及对应已注册模型，可选择yolo11s-obb.pt。
- 四类任务各使用官方YOLO11n进行1轮短微调，检查任务成功、调用参数pretrained=true及任务内模型哈希；记录见 official-yolo11-training-smoke.json。

模型加载和短微调仅证明接入流程可执行，不证明在用户数据上的准确率。s/m/l/x已完成加载及前向检查，未逐一完成训练；实际训练的显存、耗时取决于模型规模、输入尺寸、batch和任务。未新增pose训练入口。

服务器下载脚本：/hy-tmp/codex-yolo-20261112/download_yolo11.py；日志：download-yolo11.log。新机器需要单独准备权重和清单，并设置相同的目录环境变量；仅拉取Git仓库不会自动获得这些二进制权重。
