# UI 接入与兼容检查

只有替换基类、引入 ViewBinding、迁移自定义 View 或修改相关 UI 接入时加载。普通语言转换不要求执行全部项目。

## 基类的隐式能力

修改继承前，对照旧父类与新父类的实际实现及调用顺序：

| 能力 | 核对内容 |
|---|---|
| View 创建 | layout id、inflate/bind、setContentView 次数及后置钩子 |
| Context/Activity | 资源语言 Context、类型要求、旧字段与 requireContext/requireActivity 的空值和时机差异 |
| 参数与返回 | Bundle key、默认值、request code、返回消费顺序及使用的 FragmentManager |
| 自动注册 | EventBus、埋点、权限、拖拽、监听；既不能遗漏，也不能重复注册 |
| 窗口处理 | 配置变化回调、WindowInsets/刘海信息的请求、应用目标和清理时机 |

复用现有能力；目标基类缺少的必要能力做最小补齐，不把一次性逻辑塞入公共基类。新父类增加的自动副作用也要核对。

## ViewBinding 与 ButterKnife

1. 确认模块已启用 ViewBinding，读取布局及相关 qualifier/flavor；生成类与字段类型以真实生成 API 为准。纯 Canvas 绘制且不持有内部布局的 View 不必引入 Binding。
2. Activity 只创建一棵内容 View 树；基类已 inflate 时使用其真实根 View `bind`，不再单独 `inflate`。Fragment 的 Binding 按 View 生命周期持有，在 `onDestroyView` 清理。
3. 搜索目标及父子类的 `@BindView`、`@BindViews`、`@OnClick`、`@Optional`、`ButterKnife.bind`、`Unbinder`、`findViewById`。把真实静态布局引用迁到 Binding，不能只删注解留下另一套可变 View 字段。
4. 高频嵌套路径可用只读代理 getter，不能另缓存 View；protected/public 字段迁移前查继承消费者，保留必要访问契约。
5. 普通带 ID 的 `<include>` 常有子 Binding；`<merge>` 的生成方式和绑定根因布局而异，读取生成 API 后选择 `ChildBinding.bind(actualParent)`，不假定所有 include 都在根 Binding 有字段。
6. 先看 XML 真实类型，不凭 ID 判断 ViewStub。真正的 ViewStub inflate 后，用返回的 View 建立子 Binding；inflate 前不访问，View 销毁后同步清理。
7. 多布局变体的缺失节点与类型差异依生成 API 处理，不把旧 `@Optional` 假设改成强制非空。
8. 最后再移除无消费者的 ButterKnife bind/unbind、注解和 import。动态创建/替换的 View 不因“不在 Binding”被误判为未迁完。

## 生命周期、配置与异步

- Fragment 的强制非空 Binding getter 仅用于有效 View 生命周期；迟到回调先检查 nullable Binding。若 View 已重建，仅判非空不足：核对捕获的 root 或任务身份，不能把旧结果写到新 View。
- 检查 post、GlobalLayout、动画、协程与监听的取消/移除路径；一次性监听及时解除。不要为了迁移无依据地改变任务作用域和执行线程。
- 核对旧/新配置回调是否真的被宿主分发。保留旋转、窗口变化后的刷新，不以同名方法代替调用链确认。
- WindowInsets/刘海信息核对请求时点、nullable 回调、更新目标 View、方向变化和释放。沿用真实目标，不一律把边距施加到根 View。

## Java、XML 与自定义 View

- 检查 Java 构造与静态调用、checked exception 消费、字段访问、泛型与可空性；`companion object` 不自动等价于 Java 静态 API。
- XML inflate 需要的 `(Context, AttributeSet?)` 等签名必须保留。不同构造默认值可能影响主题和 defStyleAttr，不机械替换平台类或套 `@JvmOverloads`。
- 字符串属性动画、反射、XML 回调和 release 混淆按实际访问方式维护 JVM 签名与 keep 规则；debug 编译不能证明 release 可用。
- TypedArray 保持回收和异常路径。存在 stale `R.styleable` PSI 时先同步、确认真实编译；不要把临时 IDE 错误变成永久索引查询 workaround。
- AppCompat 替换或 lint 修复可能改变主题和行为；只有项目要求且确认兼容时纳入，不作为语言迁移的自动步骤。
