#!/bin/bash
# MantisBT CLI — REST API interface for mantis.inshot.com
# Usage: mantis <command> [args...]
set -euo pipefail

JSON_OUTPUT=0
JSON_EMITTED=0

_finish() {
    local code=$?
    if [[ "${code}" -ne 0 && "${JSON_OUTPUT}" -eq 1 && "${JSON_EMITTED}" -eq 0 ]]; then
        printf '{"ok":false,"error":{"code":"command_failed","message":"Mantis command failed; see stderr"}}\n'
    fi
}
trap _finish EXIT

BASE_URL="${MANTIS_BASE_URL:-https://mantis.inshot.com/api/rest/index.php}"
CONFIG_DIR="${HOME}/.config/mantis"
TOKEN_FILE="${MANTIS_TOKEN_FILE:-${CONFIG_DIR}/api-token}"

mkdir -p "${CONFIG_DIR}"

_require_jq() {
    command -v jq >/dev/null 2>&1 || {
        echo "ERROR: 需要 jq，请先安装后重试" >&2
        exit 1
    }
}

_require_token() {
    if [[ ! -s "${TOKEN_FILE}" ]]; then
        echo "ERROR: API Token 未配置。请运行: mantis setup <token-file>" >&2
        exit 1
    fi
}

_token() {
    local token
    token=$(<"${TOKEN_FILE}")
    token="${token%$'\r'}"
    [[ -n "${token}" && "${token}" != *$'\n'* && "${token}" != *$'\r'* ]] || {
        echo "ERROR: API Token 必须是单行非空文本" >&2
        return 1
    }
    printf '%s' "${token}"
}

# Token 仅经标准输入传给 curl，不进入进程参数。
_api() {
    local method="$1" path="$2"
    shift 2
    _require_token

    local body_file status body message token
    token=$(_token) || return 1
    token="${token//\\/\\\\}"
    token="${token//\"/\\\"}"
    body_file=$(mktemp "${TMPDIR:-/tmp}/mantis_api.XXXXXX")
    status=$(printf 'header = "Authorization: %s"\n' "${token}" | curl --config - -sS --max-time 30 \
        -X "${method}" \
        -H "Accept: application/json" \
        "$@" \
        -o "${body_file}" \
        -w '%{http_code}' \
        "${BASE_URL}${path}") || {
        rm -f "${body_file}"
        echo "ERROR: Mantis API 请求失败" >&2
        return 1
    }

    body=$(<"${body_file}")
    rm -f "${body_file}"

    if [[ "${status}" -lt 200 || "${status}" -ge 300 ]]; then
        message=$(printf '%s' "${body}" | jq -r '
            if type == "object" then
                .message // .localized // .error // .details // empty
            else empty end
        ' 2>/dev/null || true)
        echo "ERROR: Mantis API 返回 HTTP ${status}${message:+：${message}}" >&2
        [[ -n "${body}" && -z "${message}" ]] && printf '%s\n' "${body}" >&2
        return 1
    fi

    printf '%s' "${body}"
}

# ── Token ──────────────────────────────────────────────────

cmd_token_set() {
    local source_file="${1:-}"
    local raw

    if [[ -n "${source_file}" ]]; then
        [[ -f "${source_file}" ]] || { echo "ERROR: 文件不存在: ${source_file}" >&2; exit 1; }
        raw=$(<"${source_file}")
    else
        echo "请粘贴 MantisBT API Token，完成后按 Ctrl+D：" >&2
        raw=$(</dev/stdin)
    fi

    raw="${raw%$'\r'}"
    [[ -n "${raw}" && "${raw}" != *$'\n'* && "${raw}" != *$'\r'* ]] || {
        echo "ERROR: API Token 必须是单行非空文本" >&2
        exit 1
    }
    umask 077
    printf '%s\n' "${raw}" > "${TOKEN_FILE}"
    chmod 600 "${TOKEN_FILE}"
    echo "✅ API Token 已保存到 ${TOKEN_FILE}"
}

cmd_setup() {
    cmd_token_set "${1:-}"
    echo "正在验证 API Token……"
    cmd_check
}

cmd_token_status() {
    if [[ -s "${TOKEN_FILE}" ]]; then
        echo "API Token 已配置: ${TOKEN_FILE}"
    else
        echo "API Token 未配置"
        return 1
    fi
}

# ── Check ──────────────────────────────────────────────────

cmd_check() {
    _require_jq
    local response
    response=$(_api GET "/users/me")
    printf '%s' "${response}" | jq -r '"✅ API Token 有效   用户: \(.name)   ID: \(.id)   权限: \(.access_level.label // .access_level.name)"'
}

# ── Projects / Versions ────────────────────────────────────

_projects() {
    _api GET "/projects"
}

cmd_latest_version() {
    _require_jq
    local project_id="${MANTIS_PROJECT:-22}"

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --project|-p) project_id="$2"; shift 2 ;;
            *) echo "Unknown: $1" >&2; exit 1 ;;
        esac
    done

    local version
    version=$(_projects | jq -r --argjson project_id "${project_id}" '
        .projects[]
        | select(.id == $project_id)
        | [.versions[]? | select((.obsolete // false) == false)]
        | sort_by(.timestamp // "")
        | last
        | .name // empty
    ')
    [[ -n "${version}" ]] || { echo "ERROR: 未找到项目 ${project_id} 的版本" >&2; exit 1; }
    echo "${version}"
}

# ── List ───────────────────────────────────────────────────

cmd_list() {
    _require_jq
    local fmt="text"
    local project_id="${MANTIS_PROJECT:-22}"
    local status="" severity="" category="" version="" target_version="" fixed_version=""
    local assignee="" reporter="" hide_status="" search="" page=1 page_size=50 all=0

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --project|-p)      project_id="$2"; shift 2 ;;
            --status|-s)       status="$2"; shift 2 ;;
            --severity)        severity="$2"; shift 2 ;;
            --category|-c)     category="$2"; shift 2 ;;
            --version|-v)      version="$2"; shift 2 ;;
            --target-version)  target_version="$2"; shift 2 ;;
            --fixed-version)   fixed_version="$2"; shift 2 ;;
            --assignee|-a)     assignee="$2"; shift 2 ;;
            --reporter|-r)     reporter="$2"; shift 2 ;;
            --hide-status)     hide_status="$2"; shift 2 ;;
            --page)            page="$2"; shift 2 ;;
            --page-size|-n)    page_size="$2"; shift 2 ;;
            --search|-q)       search="$2"; shift 2 ;;
            --markdown|-m)     fmt="markdown"; shift ;;
            --all)             all=1; shift ;;
            *) echo "Unknown: $1" >&2; exit 1 ;;
        esac
    done

    [[ "${project_id}" =~ ^[0-9]+$ ]] || { echo "ERROR: project id 必须是数字" >&2; exit 1; }
    [[ "${page}" =~ ^[1-9][0-9]*$ && "${page_size}" =~ ^[1-9][0-9]*$ ]] || {
        echo "ERROR: page 和 page-size 必须是正整数" >&2
        exit 1
    }

    # 本地筛选必须遍历服务端分页；显式 --all 用于完整统计。
    local has_local_filters=0 fetch_page="${page}" fetch_page_size="${page_size}"
    if [[ -n "${status}${severity}${category}${version}${target_version}${fixed_version}${assignee}${reporter}${hide_status}${search}" ]]; then
        has_local_filters=1
    fi
    local scan_all=0
    if [[ "${has_local_filters}" -eq 1 || "${all}" -eq 1 ]]; then
        scan_all=1
        fetch_page=1
        fetch_page_size="${MANTIS_FILTER_FETCH_SIZE:-1000}"
    fi
    local max_pages="${MANTIS_MAX_PAGES:-1000}"
    [[ "${fetch_page_size}" =~ ^[1-9][0-9]*$ && "${max_pages}" =~ ^[1-9][0-9]*$ ]] || {
        echo "ERROR: fetch size 和 max pages 必须是正整数" >&2
        exit 1
    }
    [[ -z "${hide_status}" || "${hide_status}" =~ ^[0-9]+$ ]] || {
        echo "ERROR: hide-status 必须是数字" >&2
        exit 1
    }

    local response filtered collected='[]' batch count total complete=false
    while :; do
        response=$(_api GET "/issues" -G \
            --data-urlencode "project_id=${project_id}" \
            --data-urlencode "page=${fetch_page}" \
            --data-urlencode "page_size=${fetch_page_size}")
        batch=$(printf '%s' "${response}" | jq -ce '
            if type == "object" and (.issues | type) == "array" then .issues
            else error("Invalid issues response") end
        ')
        count=$(printf '%s' "${batch}" | jq 'length')
        if [[ "${count}" -eq 0 ]]; then
            complete=true
            break
        fi
        # 服务端忽略页码时失败退出，不能把重复页当成完整列表。
        if [[ "${scan_all}" -eq 1 ]] && ! printf '%s\n%s\n' "${collected}" "${batch}" | jq -se '
            (.[0] | map(.id)) as $seen |
            (.[1] | (length == (unique_by(.id) | length)) and
                all(.[]; .id != null and (.id as $id | $seen | index($id) == null)))
        ' >/dev/null; then
            echo "ERROR: 分页返回重复或缺少 ID，未获得完整列表" >&2
            return 1
        fi
        collected=$(printf '%s\n%s\n' "${collected}" "${batch}" | jq -sc '.[0] + .[1]')
        [[ "${scan_all}" -eq 1 ]] || break
        if [[ "${fetch_page}" -ge "${max_pages}" ]]; then
            echo "ERROR: 已达分页上限 ${max_pages}，未获得完整列表" >&2
            return 1
        fi
        fetch_page=$((fetch_page + 1))
    done

    filtered=$(printf '{"issues":%s}' "${collected}" | jq \
        --arg status "${status}" \
        --arg severity "${severity}" \
        --arg category "${category}" \
        --arg version "${version}" \
        --arg target_version "${target_version}" \
        --arg fixed_version "${fixed_version}" \
        --arg assignee "${assignee}" \
        --arg reporter "${reporter}" \
        --arg hide_status "${hide_status}" \
        --arg search "${search}" '
        def matches_ref($value; $query):
            ($query == "") or
            (($value.id? | tostring) == $query) or
            (($value.name? // "" | ascii_downcase) == ($query | ascii_downcase)) or
            (($value.label? // "" | ascii_downcase) == ($query | ascii_downcase));
        def contains_text($value; $query):
            ($query == "") or (($value // "" | ascii_downcase) | contains($query | ascii_downcase));

        [.issues[]
            | select(matches_ref(.status; $status))
            | select(matches_ref(.severity; $severity))
            | select(matches_ref(.category; $category))
            | select($version == "" or (.version.name? // "") == $version)
            | select($target_version == "" or (.target_version.name? // "") == $target_version)
            | select($fixed_version == "" or (.fixed_in_version.name? // "") == $fixed_version)
            | select(matches_ref(.handler; $assignee))
            | select(matches_ref(.reporter; $reporter))
            | select($hide_status == "" or ((.status.id // 0) < ($hide_status | tonumber)))
            | select($search == "" or contains_text(.summary; $search) or contains_text(.description; $search))
        ]
    ')

    total=$(printf '%s' "${filtered}" | jq 'length')
    [[ "${scan_all}" -eq 1 ]] || total=null
    if [[ "${has_local_filters}" -eq 1 && "${all}" -eq 0 ]]; then
        local offset=$(( (page - 1) * page_size ))
        filtered=$(printf '%s' "${filtered}" | jq --argjson offset "${offset}" --argjson limit "${page_size}" '.[$offset:($offset + $limit)]')
    fi

    if [[ "${JSON_OUTPUT}" -eq 1 ]]; then
        printf '%s' "${filtered}" | jq \
            --argjson page "${page}" --argjson page_size "${page_size}" \
            --argjson total "${total}" --argjson complete "${complete}" --argjson all "${all}" '
            {ok: true, issues: ., count: length,
             pagination: {page: (if $all == 1 then null else $page end),
                          page_size: (if $all == 1 then null else $page_size end),
                          total: $total, complete: $complete, all: ($all == 1)}}'
        JSON_EMITTED=1
    elif [[ "${fmt}" == "markdown" ]]; then
        printf '| ID | 优先级 | 严重程度 | 负责人 | 状态 | 摘要 |\n'
        printf '|---:|---|---|---|---|---|\n'
        printf '%s' "${filtered}" | jq -r '.[] |
            "| \(.id) | \(.priority.label // .priority.name // "-") | \(.severity.label // .severity.name // "-") | \(.handler.real_name // .handler.name // "-") | \(.status.label // .status.name // "-") | \((.summary // "") | gsub("\\|"; "\\|")) |"'
    else
        printf '%s' "${filtered}" | jq -r '.[] |
            "\(.id) | \(.priority.label // .priority.name // "-") | \(.severity.label // .severity.name // "-") | \(.handler.real_name // .handler.name // "-") | \(.status.label // .status.name // "-") | \(.summary // "")"'
    fi

    count=$(printf '%s' "${filtered}" | jq 'length')
    if [[ "${scan_all}" -eq 1 ]]; then
        echo "本页 ${count} 个问题；完整筛选结果共 ${total} 个" >&2
    else
        echo "本页 ${count} 个问题；总数未统计（完整统计使用 --all）" >&2
    fi
}

# ── View ───────────────────────────────────────────────────

cmd_view() {
    _require_jq
    local bug_id="${1:-}"
    [[ -n "${bug_id}" ]] || { echo "Usage: mantis view <bug-id>" >&2; exit 1; }

    _api GET "/issues" -G --data-urlencode "id=${bug_id}" | jq -r '
        .issues[0] as $i
        | if $i == null then error("问题不存在") else
          "#\($i.id) \($i.summary)\n\n" +
          "── 基本信息 ──\n" +
          "  项目      \($i.project.name // "-")\n" +
          "  分类      \($i.category.name // "-")\n" +
          "  严重性    \($i.severity.label // $i.severity.name // "-")\n" +
          "  优先级    \($i.priority.label // $i.priority.name // "-")\n" +
          "  状态      \($i.status.label // $i.status.name // "-")\n" +
          "  分派给    \($i.handler.real_name // $i.handler.name // "-")\n" +
          "  报告员    \($i.reporter.real_name // $i.reporter.name // "-")\n" +
          "  产品版本  \($i.version.name // "-")\n" +
          "  目标版本  \($i.target_version.name // "-")\n" +
          "  修正版本  \($i.fixed_in_version.name // "-")\n\n" +
          "── 描述 ──\n\($i.description // "")" +
          (if (($i.notes // []) | length) > 0 then
              "\n\n── 注释 ──\n" + ([$i.notes[] | "  - [\(.reporter.real_name // .reporter.name // "-")] \(.text)"] | join("\n"))
           else "" end)
          end
    '
}

# ── Note / Update ──────────────────────────────────────────

cmd_note() {
    _require_jq
    local bug_id="${1:-}"
    [[ $# -gt 0 ]] && shift
    local note_text="$*"
    [[ -n "${bug_id}" && -n "${note_text}" ]] || {
        echo "Usage: mantis note <bug-id> <text>" >&2
        exit 1
    }

    local payload
    payload=$(jq -n --arg text "${note_text}" '{text: $text, view_state: {name: "public"}}')
    _api POST "/issues/${bug_id}/notes" \
        -H "Content-Type: application/json" \
        --data "${payload}" >/dev/null || return 1
    if [[ "${JSON_OUTPUT}" -eq 1 ]]; then
        jq -n --arg id "${bug_id}" '{ok: true, issue_id: $id, steps: {note: "completed"}}'
        JSON_EMITTED=1
    else
        echo "✅ Bug ${bug_id} 注释已添加"
    fi
}

_status_id() {
    case "$1" in
        新建|new|10) echo 10 ;;
        反馈|feedback|20) echo 20 ;;
        认可|acknowledged|30) echo 30 ;;
        已修改|modified|40|已确认) echo 40 ;;
        已分配|assigned|50) echo 50 ;;
        已解决|resolved|80) echo 80 ;;
        已关闭|closed|90) echo 90 ;;
        *) [[ "$1" =~ ^[0-9]+$ ]] && echo "$1" || return 1 ;;
    esac
}

_update_result() {
    local bug_id="$1" success="$2" status_step="$3" note_step="$4" message="$5"
    if [[ "${JSON_OUTPUT}" -eq 1 ]]; then
        jq -n --arg id "${bug_id}" --argjson ok "${success}" \
            --arg status "${status_step}" --arg note "${note_step}" --arg message "${message}" '
            {ok: $ok, issue_id: $id, steps: {status: $status, note: $note}} +
            (if $ok then {} else {error: {code: "update_incomplete", message: $message}} end)'
        JSON_EMITTED=1
    fi
    if [[ "${success}" == "true" ]]; then
        [[ "${JSON_OUTPUT}" -eq 1 ]] || echo "✅ Bug ${bug_id} 已更新"
    else
        echo "ERROR: ${message}（状态=${status_step}，注释=${note_step}）；先回读核对，不要重试整个写操作" >&2
    fi
}

cmd_update() {
    _require_jq
    local bug_id="${1:-}"
    [[ $# -gt 0 ]] && shift
    [[ -n "${bug_id}" ]] || { echo "Usage: mantis update <bug-id> [--status <s>] [--note <t>]" >&2; exit 1; }

    local status="" note_text=""
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --status|-s) status="$2"; shift 2 ;;
            --note|-n) note_text="$2"; shift 2 ;;
            *) echo "Unknown: $1" >&2; exit 1 ;;
        esac
    done
    [[ -n "${status}" || -n "${note_text}" ]] || { echo "至少需要 --status 或 --note" >&2; exit 1; }

    local status_step="not_requested" note_step="not_requested"
    [[ -z "${status}" ]] || status_step="not_attempted"
    [[ -z "${note_text}" ]] || note_step="not_attempted"
    if [[ -n "${status}" ]]; then
        local sid payload current
        sid=$(_status_id "${status}") || { echo "ERROR: 不支持的状态: ${status}" >&2; return 1; }
        payload=$(jq -n --argjson sid "${sid}" '{status: {id: $sid}}')
        if ! _api PATCH "/issues/${bug_id}" \
            -H "Content-Type: application/json" \
            --data "${payload}" >/dev/null; then
            _update_result "${bug_id}" false unknown "${note_step}" "状态请求失败，服务端结果待核对"
            return 1
        fi

        if ! current=$(_api GET "/issues" -G --data-urlencode "id=${bug_id}" | jq -er '.issues[0].status.id'); then
            _update_result "${bug_id}" false unverified "${note_step}" "状态请求已接受，但回读失败"
            return 1
        fi
        if [[ "${current}" != "${sid}" ]]; then
            _update_result "${bug_id}" false unverified "${note_step}" "状态回读不一致，期望=${sid}，当前=${current}"
            return 1
        fi
        status_step="completed"
    fi

    if [[ -n "${note_text}" ]]; then
        if ! cmd_note "${bug_id}" "${note_text}" >/dev/null; then
            _update_result "${bug_id}" false "${status_step}" unknown "注释请求失败，可能部分成功；先检查注释是否已写入"
            return 1
        fi
        note_step="completed"
    fi

    _update_result "${bug_id}" true "${status_step}" "${note_step}" ""
}

# ── Search ─────────────────────────────────────────────────

cmd_search() {
    [[ $# -gt 0 ]] || { echo "Usage: mantis search <query> [list options]" >&2; exit 1; }
    local search_query="$1"
    shift
    cmd_list --search "${search_query}" "$@"
}

# ── Help ───────────────────────────────────────────────────

cmd_help() {
    cat <<'HELP'
MantisBT CLI — 通过 REST API Token 访问 mantis.inshot.com

用法:
  mantis <command> [args...]

Token 管理:
  setup [token-file]      保存并验证 API Token
  token-set [token-file]  从文件或标准输入保存 API Token
  token-status            查看 Token 配置状态（不会显示 Token）
  check                   验证 API Token

查看:
  list [options]          列出问题
  latest-version          获取项目最新版本
  view <bug-id>           查看详情
  search <query>          搜索

操作:
  note <bug-id> <文本>    添加注释
  update <bug-id>         更新状态
    --status|-s <状态>     assigned/resolved/closed/new（或状态 ID）
    --note|-n   <文本>    同时添加注释

list 选项:
  --status|-s      <值>    状态 ID 或名称
  --assignee|-a    <值>    负责人 ID 或名称
  --reporter|-r    <值>    报告人 ID 或名称
  --project|-p     <id>    项目 ID
  --version|-v     <文本>  产品版本
  --target-version <文本>  目标版本
  --fixed-version  <文本>  修正版本
  --category|-c    <值>    分类 ID 或名称
  --severity       <值>    严重程度 ID 或名称
  --search|-q      <文本>  搜索标题和描述
  --hide-status    <id>    隐藏状态 ID >= 指定值的问题
  --page           <num>   页码
  --page-size|-n   <num>   每页条数（正整数）
  --all                    返回完整筛选结果，不做展示分页
  --json                   list/search/note/update 输出机器可读 JSON
  --markdown|-m             输出 Markdown 表格

筛选会遍历服务端分页；MANTIS_FILTER_FETCH_SIZE 为抓取页大小，
MANTIS_MAX_PAGES 为抓取上限，达到上限或分页失败时非零退出，不输出部分列表。
update 的状态和注释分步执行；失败须核对 steps，不要直接重试整个操作。

示例:
  mantis setup '/path/to/token.txt'
  mantis list --project 22 --status 50 --assignee 298 -m
  mantis latest-version --project 22
  mantis list --project 22 --target-version '<版本名>' -m
  mantis view 198148
  mantis note 198148 '已修复，请验证'
  mantis update 198148 --status resolved -n '修复完成'
  mantis search 'ANR' --project 22
HELP
}

# ── Main ───────────────────────────────────────────────────

main() {
    [[ $# -gt 0 ]] || { cmd_help; exit 0; }
    local cmd="$1"
    shift
    local args=() arg
    for arg in "$@"; do
        if [[ "${arg}" == "--json" ]]; then
            JSON_OUTPUT=1
        else
            args+=("${arg}")
        fi
    done
    set -- "${args[@]}"
    if [[ "${JSON_OUTPUT}" -eq 1 && "${cmd}" != "list" && "${cmd}" != "ls" && "${cmd}" != "search" && "${cmd}" != "grep" && "${cmd}" != "note" && "${cmd}" != "comment" && "${cmd}" != "update" && "${cmd}" != "modify" ]]; then
        echo "ERROR: --json 仅支持 list/search/note/update" >&2
        return 1
    fi
    case "${cmd}" in
        setup|init)                  cmd_setup "$@" ;;
        token-set|token-setup)       cmd_token_set "$@" ;;
        token-status)                cmd_token_status ;;
        list|ls)                     cmd_list "$@" ;;
        latest-version|latest|lv)    cmd_latest_version "$@" ;;
        view|show)                   cmd_view "$@" ;;
        search|grep)                 cmd_search "$@" ;;
        note|comment)                cmd_note "$@" ;;
        update|modify)               cmd_update "$@" ;;
        check|test)                  cmd_check ;;
        help|--help|-h)              cmd_help ;;
        cookie-set|cookie-show)
            echo "Cookie 认证已停用，请使用: mantis setup <token-file>" >&2
            exit 1
            ;;
        *) echo "Unknown: ${cmd}" >&2; cmd_help >&2; exit 1 ;;
    esac
}

main "$@"
