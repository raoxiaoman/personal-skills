# VideoGuru 埋点契约

这些是既有项目约定的定位线索，不是所有 Android/Firebase 项目的通用 API 保证。修改前核对目标工作区当前源码；符号关系优先当前项目的 IDE 索引，索引失败或项目不符才退回文本搜索。

## select_content

当需求明确写“放在 select_content”时，核对以下映射：

| 需求 | Firebase 字段 |
|---|---|
| 事件名 | `select_content` |
| 业务 key | `content_type` |
| 操作值 | `item_id` |

既有封装中 `AppTrack.logSimpleEvent("denoise", "finish")` 用于该映射；`AppTrack.logEvent("denoise", "finish")` 则会以 `denoise` 为事件名。先读当前方法实现确认，不因调用看起来相近就替换。

项目查看器曾用 `eventName !== 'select_content'` 标注“外部”；这里指自定义事件名，不表示发送到 Firebase 之外。只有需求本身要求自定义事件时才按对应 event name 上报，不把所有业务强制塞进 select_content。

## 定位链路

按功能范围核对实际消费者，不机械全仓审查：

- `Guru/src/main/java/com/camerasideas/utils/newutils/AppTrack.kt`
- `Guru/src/main/java/com/camerasideas/instashot/compat/UtTrackFirebaseImpl.kt`
- `Guru/src/main/java/com/camerasideas/instashot/compat/AnalyticsFilterCompat.kt`
- `Guru/src/main/java/com/camerasideas/instashot/ISFirebaseListener.java`
- 初始化或依赖挂接缺口再看 `startup/InitializeApmTask.java`、`UtDependencyInjection.kt`。

常见链路为业务 → AppTrack → UtTrackFirebaseImpl → AnalyticsFilter → FirebaseAnalytics；旧入口可能经 FirebaseUtil → ISFirebaseListener → AnalyticsFilterCompat。当前代码是依据，路径不存在时重新定位，不创建同名替身。

## 触发与分类

需求若规定 Retry 不计 start，则沿真实首次发起/重试链区分；成功、失败是否计数另外核对。完成或最终状态埋点，需防止把旧 Completed 恢复当成本次新处理，不能只凭 Fragment 是否正在移除判断一次性。

复用既有业务错误分类，例如需求规定的 `server`、`network`、`unknown`；不能把具体功能的“无人声”等错误默认归 unknown，也不发送原始错误文本。

## 过滤与查看器

既有包内过滤资源为 `Guru/src/main/assets/analytics_filter_config_android.json`，还可能受下载配置、采样和运行时门控影响。Debug 日志出现不证明过滤后发送；缺日志也不能直接判漏埋。修改过滤资源、版本或云端链路是额外变更，不因加事件而自动执行。

`script/Firebase埋点查看器/` 可作为格式线索，但启动器可能修改 Firebase Debug 属性或开启服务。默认不启动、不导入其 server，不把历史端口或设备当当前配置；需要 GUI 时先核对当前行为与授权。
