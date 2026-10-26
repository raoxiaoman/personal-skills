# GPUImage 条件接入参考

仅在目标工程确实使用 GPUImage 或其分支时读取。下列类名来自旧技能的项目经验，是查找线索而非已经核实的当前 API；从真实定义和调用方确认签名，不跨仓库复制历史实现。

## 找到工程的真实扩展点

- 定位 Filter 父类、Group、注册/配置解析和 Shader 加载路径。旧经验中的 `GPUEffectFilter`、`GPUEffectFilterGroup`、`EffectFilterRegistry`、`ShaderKey` 不一定存在于其他分支，不能假装是 GPUImage 标准 API。
- 核对初始化、uniform 位置与供值、`setRelativeTime` 或等价更新、`updateEffectProperty`、draw 和 destroy。是否调用父类及先后顺序以真实能力为准，不为消除警告删掉隐含初始化/释放。
- 配置解析、注册键和 Shader/native 产物只有真实消费者需要才修改。Shader 加密/构建可能附带跨项目复制，先查副作用，不能因用户要求开发就覆盖其他仓库。

## 滤镜链与范围外输出

区分原图效果链和素材混合链。旧分支的 `GPUMixEffectFilter` 可选择 lookup、视频、图片的叠加顺序；先读当前实现及枚举，不硬编码数值、默认顺序或凭名字推断支持能力。

时间范围外选择终态保持或原图透传；需要输出却直接 return 可能留下黑屏或复用旧内容，但外层已有旁路时不能再额外重复输出。检查 pass 的实际 FBO 与提交契约。

Group 和子 Filter 对时间的消费可能不同：旧实现曾用循环相对时间判活动范围、向子滤镜传原始时间。接入时确认由哪一层取模，防止重复折算、末边界回零或子链时间漂移。

## 多纹理分割的两阶段

旧实现中，分割视频不只是配置一个 JSON 字段：

1. 合成阶段解析裁剪配置，把一帧分割为多张纹理，并生成对应属性。
2. Filter 阶段逐段消费这些纹理及混合信息，再按定义顺序合成。

可搜索 `splitVideoProperty`、`VideoEffectMultiTextureCropConverter`、`textureIdList`、`extraPropertyList` 追踪实际生产与消费。确认列表长度、索引对应、裁剪空间、尺寸、混合模式和纹理有效生命周期；输入段数减少、配置更新或失败时不能沿用旧纹理/旧参数。

不要推断所有 `GPUMixEffectFilter` 都支持分割：旧版本只有一个视频混合 Filter 且没有读取纹理列表。当前版本是否仍如此需读代码；也不要固定“一段一个 Filter”作为所有管线必须的架构。

## 素材和关键帧

- lookup、视频、遮罩和图片分别核对真实文件、尺寸、alpha、裁剪与混合含义；横/竖/方素材选择取决于当前配置消费者。数字 blendType/cropType 不是跨项目通用协议。
- 本地资源名称、扩展名、包结构及加密绑定遵循项目实际加载器；不要为统一样式重命名已持久化引用，也不把某个平台都“大小写敏感/不敏感”当命名依据。
- `KeyframeTrack`、`EffectFrameTimePoint` 只是已有框架线索。读取真实 `getValue`、`getValueByFrame`、曲线归属、空返回与循环策略，使用[关键帧流程](keyframes.md)，不再另写 `FrameTimePoint` 框架。

## 验证边界

先用实际构建入口验证宿主类型、资源/Shader 键和 native 接口，再检查初始、活动段、末态、重置、seek、多个尺寸与预览/导出。纹理/FBO 的视觉和性能结论需要真实运行证据。

源码路径、包名、生成器命令与发布目标留在项目规则。此参考不提供上传、远端删除、缓存刷新或自动确认命令；需要分发时另按授权核实目标、产物与恢复条件。
