# 项目定位

本项目是一个多任务视觉训练智能体,用于实现:

图片->标注->数据集->yolo训练(detect/segment/obb)->模型评估-主动学习迭代

这是一个工程化AI应用,不是简单标注工具

核心目标:

构建一个从数据到模型的自动化闭环系统(Human-in-the-loop)

# 技术栈

frontend:

- vue,typescrip


- vue-konva(标注画布)



backend:

- fastapi


- python3.10+



AI/CV:

- Ultralytics yolo


- ONNX runtime


- opencv



Storage:

- PostgreSQL
- 文件系统



# Python环境约束

所有Python依赖必须安装在conda环境中,禁止安装到系统环境

# 目录结构约定

backend/
app/
api/ # HTTP API
core/#通用组件(config/logger)
dataset/#数据集管理
dataset/exchange/ # 数据集导入导出 (native / coco / archive / splits)
annotation/#标注逻辑
yolo/#YOL0 相关(导入导出/格式转换/引擎封装)
training/#训练任务
models/#模型版本管理
evaluation/#模型评估与错误样本
quality/#标注质量与数据集报告
validation/#数据校验规则与数据集验证
auto_annotation/#自动标注任务
active_learning/# 主动学习任务
sam/#SAM 推理能力
settings/#LLM/系统设置
agent/#Agent能力(工具/调度)



frontend/
src/
pages/
components/
annotation/#标注UI(核心)
api/
types/



# 核心设计原则

- Agent是调度者,不是执行者
- Tool-first:所有能力通过tool暴露
- 严禁跨层调用,遵守模块边界

所有能力必须工具化

dataset.validate
dataset.summary
annotation.export_yolo
dataset.quality_reportdataset.diagnose_qualitydataset.class_balance
dataset.annotation_gap
dataset.exchange.export_native
training.start
training.status
training.logs
training.latest_result
training.diagnose_failure
evaluation.start
evaluation.summary
evaluation.latest
evaluation.error_summary
evaluation.pose_keypoint_summary
active_learning.start
active_learning.recommend
model.latest_for_dataset
model.compare
model.export_onnx
workflow.status

workflow.finnal_report

# 数据与标注规范

- 内部使用绝对坐标存储
- 导出到yolo时进行归一化
- Task Type统一管理,禁止硬编码

annotation数据规范

内部格式(绝对坐标)
支持 type:"bbox",type:"polygon",type:"obb",type:"pose" 与 type:"classify"

- bbox/polygon/obb/pose使用图片原始尺寸下的绝对坐标。
- pose 当前可表达 bbox + keypoints，并已进入校验、导出和评估诊断链路:但整体成熟度仍低于detect/segment/obb/classiy主链路。
- classify是图片级标签，一张图第一版只允许一个classify annotation，
- 同一张图中，classify不能与 bbox/polygon/obb/pose 混用。

```
{
  "image_id": "xxx",
  "annotations": [
    {
      "type": "bbox",
      "class_id": "class_001",
      "class_index": 0,
      "bbox": {
        "x": 100,
        "y": 120,
        "width": 300,
        "height": 400
      },
      "source": "manual"
    },
    {
      "type": "polygon",
      "class_id": "class_001",
      "class_index": 0,
      "polygon": [[100, 120], [400, 120], [400, 520], [100, 520]],
      "source": "manual"
    },
    {
      "type": "obb",
      "class_id": "class_002",
      "class_index": 1,
      "obb": {
        "cx": 320,
        "cy": 240,
        "width": 180,
        "height": 80,
        "angle": 15
      },
      "source": "manual"
    },
    {
      "type": "pose",
      "class_id": "class_002",
      "class_index": 1,
      "bbox": {
        "x": 120,
        "y": 140,
        "width": 220,
        "height": 320
      },
      "keypoints": [
        { "name": "nose", "x": 220, "y": 180, "visible": 2 }
      ],
      "source": "manual"
    },
    {
      "type": "classify",
      "class_id": "class_003",
      "class_index": 2,
      "source": "manual"
    }
  ]
}
```

YOLO 导出 (归一化)
detect: class_index x_center y_center width height

segment: class_index x1 y1 x2 y2 ...

obb: class_index x1 y1 x2 y2 x3 y3 x4 y4

pose: class_index bbox + keypoints + visible

classify: train/<class_name>/... 、 val/<class_name>/...

自动任务类型推断规则：

- 如果数据集只有一种 annotation family，则由该 family 推断 task_type 。
- 如果数据集没有标注，默认按 detect 处理。

- 如果数据集混用了多种 annotation family，必须报错或要求显式指定 task_type，不能按优先级静默猜测。

- 如果用户显式传入 task_type，必须校验数据集内是否存在对应 annotation 类型；不要静默导出空任务。


数据集 split 约束：

- 数据集 train / val / test 划分应持久化保存。
- 导出器（YOLO / native / COCO）应优先读取已有 split，而不是每次都重新随机切分。


annotation / yolo 转换层必须提供成对转换接口：

- to_yolo()


- from_yolo()

# 训练任务规范

- 通过统一接口启动训练

training.start training.status training.logs training.latest_result training.diagnose_failure

训练后协作链路通过各自Tools衔接:

evaluation.start evaluation.summary evaluation.latest active leaning. start modellatest for dataset model.compare workfiow.status worktiow.final report

- 禁止

在api层直接调用yolo train

- 训练状态,日志,指标必须可查询

# 标注前端规范

必须支持:

- bbox:创建,拖拽,resize
- Polygon:绘制与编辑(分割标注)
- obb:创建,拖拽,resize,旋转,角度输入
- pose:关键点绘制,编辑,可见性处理,schema对齐
- 类别切换,保存

# 编码规范

- 避免巨型函数,保持单一职责,<100行
- IO操作(文件读写,数据库操作,训练调用)必须封装,禁止散落在业务逻辑中,必须在独立模块中
- 不随意修改无关文件,保持最小变更
- 不要重复造轮子,优先使用Ultralytics opencv pydantic
- 明确类型定义def create_annotation(data: AnnotationCreateRequest) -> Annotation:
- 放过度防御:几乎不会发生的边界/并发问题,讲清概率并经用户确认后再加,严禁未"理论上更稳"私自膨胀代码
- 入口单次校验:外部数据只在边界校验一次,内部靠类型系统流转,禁止层层重复判断
- 拒绝提前抽象:单次使用的逻辑就近内联,不随意提前拆分无意义的helper
- 控制复杂度:非必要不用try/catch,能单函数清晰搞定的别硬拆


