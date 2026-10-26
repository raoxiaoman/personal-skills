# 渲染契约

供三个入口按风险读取，不要求每次填写整张表。以真实 vertex/fragment、纹理生产者和调用方为证据；没有依据的字段标为未知，不生成一套假想接口。

## 输入、坐标与采样

- 确认 GLES/GLSL 版本与扩展，纹理是 `sampler2D`、外部纹理还是其他类型；外部纹理的 shader 声明、扩展和采样限制不能照搬二维纹理。
- 确认 UV 是归一化、像素、裁剪后坐标还是每输入独立坐标；跟踪旋转、镜像、裁剪和顶点变换，避免应用两次。归一化 UV 不需再除尺寸，但邻域采样/宽高比依赖实际输入或输出尺寸，不能一概禁止分辨率。
- 记录纹理尺寸、min/mag filter、wrap 与 mipmap。ES2 基础 NPOT 纹理通常要求 `CLAMP_TO_EDGE` 和非 mipmap min filter；需要 repeat/mirrored repeat 或 mipmap 时核对对应扩展、纹理条件及真实驱动支持。
- `GL_MIRRORED_REPEAT` 是一种视觉采样策略，不是通用边缘修复。修改借入纹理的参数会影响后续消费者，先确认所有权或约定恢复/独立纹理。

## 颜色、alpha 与输出

确认输入颜色编码、目标附件格式、alpha 表示及 blend enable/factors。不要把 UI 颜色值、编码/线性空间和纹理格式当成同一概念；只在任务涉及、且有真实证据时引入转换。

straight-alpha 输入合成到 premultiplied 输出时，RGB 贡献示意为 `Cs * As + Cd_p * (1 - As)`，alpha 为 `As + Ad * (1 - As)`；premultiplied 输入已含 `Cs * As`，不能再乘一次。若要 straight 输出需处理结果 alpha 为零，再按真实格式转换。以上是 source-over 例，不替代项目实际混合模式与 GL 因子检查。

范围外 RGB、UV 或 progress 可能有意。先核对纹理格式及后续消费者，再决定 clamp、mask、透传或保留，不加无依据的全局范围限制。

## 精度与语言版本

ES2 对应 GLSL ES 1.00；vertex/fragment 的 varying 类型和精度须匹配。fragment highp 并非所有 ES2 目标都支持。`GL_FRAGMENT_PRECISION_HIGH` 可用于条件选择，host 也可查询精度；降为 mediump 仍须检查算法动态范围、UV 分辨能力和目标设备视觉，不能保证退化后效果一致。

GLSL 内置 `mod` 的负值语义与 Java/Kotlin `%` 不同；跨 host/shader 转换时间时明确归一化策略。不要把桌面 OpenGL、Vulkan/SPIR-V 编译结果当 ES2 编译或链接证据。

## pass、状态与资源归属

- 明确每个 pass 的读写纹理、FBO、viewport 与输出尺寸，防止采样同一附件的未定义反馈。复用池中资源要确认尺寸/格式和清理规则。
- 谁设置 GL 状态、谁承诺恢复由管线契约决定，不在每个 pass 盲目保存恢复。对象状态和 context 绑定不同，解绑不撤销纹理参数修改。
- 确认 GL context/线程、初始化/更新/释放、异步上传与销毁顺序；context 丢失后的缓存 ID 不能当有效资源。
- 需要输出的时间段外也必须有有效输出；只有外层负责 bypass 时才可以省略当前 pass。保持末态与透传按效果契约选择。

## 验证证据

分开报告：参数/数学样例、源代码检查、离线目标编译、真实 shader compile/link、Android/native 构建、设备视觉、性能与预览/导出一致性。任一层通过不代表其他层通过。性能测量说明设备、分辨率、效果链和输入条件；缺工具就明确缺口，不临时更换 profile 冒充验证。
